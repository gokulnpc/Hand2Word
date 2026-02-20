import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from strands import Agent
from strands.handlers.callback_handler import PrintingCallbackHandler

from services.redis_manager import RedisManager
from services.commit_engine import CommitEngine
from services.word_resolver import WordResolver
from models import LetterPrediction, WordBuffer, ResolvedWord, SearchResult

logger = logging.getLogger(__name__)


class FingerspellingAgent:
    """
    Strands-powered agent for intelligent ASL fingerspelling word resolution.
    
    Pipeline:
    1. Consumes letter predictions from Kinesis letters stream
    2. Uses commit engine to stabilize letter sequences into word stems
    3. Agent reasons about potential confusions and generates alias candidates
    4. Queries personalized MongoDB lexicon with fuzzy + autocomplete search
    5. Returns top N most confident word matches to user
    """
    
    def __init__(
        self,
        redis_manager: RedisManager,
        commit_engine: CommitEngine,
        word_resolver: WordResolver,
        enable_streaming: bool = True
    ):
        """
        Initialize the Fingerspelling Agent.
        
        Args:
            redis_manager: Manages sliding window state in Redis
            commit_engine: Stabilizes letter sequences into word stems
            word_resolver: Queries MongoDB Atlas with fuzzy search
            enable_streaming: Enable real-time event streaming for debugging
        """
        self.redis_manager = redis_manager
        self.commit_engine = commit_engine
        self.word_resolver = word_resolver
        self.enable_streaming = enable_streaming
        
        # Initialize Strands Agent with custom callback handler
        self.agent = self._initialize_agent()
        
        logger.info("✓ Fingerspelling Strands Agent initialized")
    
    def _initialize_agent(self) -> Agent:
        """
        Initialize Strands Agent with fingerspelling-specific tools and configuration.
        """
        # Custom callback handler for streaming events
        def fingerspelling_callback(**kwargs):
            """Stream handler for agent reasoning and tool usage"""
            # Track reasoning process
            if kwargs.get("reasoning", False):
                reasoning_text = kwargs.get("reasoningText", "")
                if reasoning_text:
                    logger.debug(f"🧠 Agent reasoning: {reasoning_text[:100]}")
            
            # Track tool usage
            if "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
                tool_name = kwargs["current_tool_use"]["name"]
                logger.info(f"🔧 Agent using tool: {tool_name}")
            
            # Stream agent output
            if "data" in kwargs:
                logger.debug(f"📟 Agent output: {kwargs['data'][:50]}")
            
            # Track message completion
            if "message" in kwargs and kwargs["message"].get("role") == "assistant":
                logger.debug(f"📬 Agent completed message")
        
        # Create agent with callback (or None for silent mode)
        callback_handler = fingerspelling_callback if self.enable_streaming else None
        
        agent = Agent(
            tools=[
                self._create_lexicon_search_tool(),
                self._create_confusion_analysis_tool(),
                self._create_buffer_inspection_tool()
            ],
            callback_handler=callback_handler,
            model="claude-sonnet-4-20250514",  # Use latest Claude model
            system_prompt=self._get_system_prompt()
        )
        
        return agent
    

    def _get_system_prompt(self) -> str:
        """
        System prompt that teaches the agent about ASL fingerspelling challenges.
        """
        return """You are an expert ASL (American Sign Language) fingerspelling recognition assistant.

Your role is to help resolve ambiguous fingerspelled letter sequences into real words from the user's personalized lexicon.

Key challenges in ASL fingerspelling:
1. **Visual confusions**: Similar hand shapes are easily confused
   - W ↔ 6 (three fingers vs six motion)
   - A ↔ E (thumb position varies)
   - M ↔ N (number of fingers tucked)
   - S ↔ T (thumb position)
   - K ↔ P ↔ V (finger orientations)

2. **Incomplete sequences**: Users may pause/commit before finishing
   - "A" → could be "AI", "API", "AWS", "ASL", etc.
   - "AW" → could be "AWS", "AWARDS", etc.

3. **Motion blur and occlusion**: Fast signing creates prediction errors
   - Double letters: "AWWS" → "AWS"
   - Substitutions: "AWX" → "AWS"

Your task:
1. Analyze the committed letter sequence
2. Consider likely confusions based on ASL confusion matrix
3. Generate semantically meaningful alias candidates
4. Query the user's personalized lexicon
5. Return top 5 most confident matches with hybrid scores (70% text similarity + 30% confusion confidence)

Always prioritize:
- User's actual vocabulary (personalized lexicon)
- Common ASL confusions over random typos
- Context from user's domain (e.g., tech terms for developers)
"""
    
    def _create_lexicon_search_tool(self):
        """
        Tool that allows agent to query MongoDB lexicon with adaptive search.
        """
        def search_lexicon(query: str, strategy: str = "auto") -> Dict[str, Any]:
            """
            Search user's personalized lexicon for matching words.
            
            Args:
                query: The letter sequence to search for
                strategy: Search strategy - "auto" (adaptive), "autocomplete", or "fuzzy"
            
            Returns:
                Dictionary with top matching results and their scores
            """
            try:
                # Create a mock buffer for word resolver
                buffer = WordBuffer(
                    session_id="agent_query",
                    user_id="agent_user",
                    letters=list(query.upper())
                )
                
                # Use word resolver to query MongoDB
                resolved = self.word_resolver.resolve_word(buffer, search_method=strategy)
                
                # Format results for agent
                results = {
                    "raw_query": query,
                    "num_results": len(resolved.all_results),
                    "results": [
                        {
                            "surface": r.surface,
                            "atlas_score": r.atlas_score,
                            "alias_confidence": r.alias_confidence,
                            "hybrid_score": r.hybrid_score,
                            "matched_via": r.matched_via
                        }
                        for r in resolved.all_results[:5]
                    ]
                }
                
                logger.info(f"🔍 Lexicon search: '{query}' → {len(resolved.all_results)} results")
                return results
            
            except Exception as e:
                logger.error(f"Error in lexicon search: {e}")
                return {"error": str(e), "results": []}
        
        return search_lexicon
    
    def _create_confusion_analysis_tool(self):
        """
        Tool that analyzes potential ASL character confusions.
        """
        # ASL confusion matrix (simplified)
        CONFUSION_PAIRS = {
            'W': ['6', 'V'],
            '6': ['W', 'V'],
            'A': ['E', 'S'],
            'E': ['A'],
            'M': ['N'],
            'N': ['M'],
            'S': ['A', 'T'],
            'T': ['S'],
            'K': ['P', 'V'],
            'P': ['K', 'V'],
            'V': ['K', 'P', '6', 'W']
        }
        
        def analyze_confusions(letter_sequence: str) -> Dict[str, Any]:
            """
            Analyze potential character confusions in the letter sequence.
            
            Args:
                letter_sequence: The raw letter sequence (e.g., "AWX")
            
            Returns:
                Dictionary with confusion analysis and suggested alternatives
            """
            alternatives = []
            sequence_upper = letter_sequence.upper()
            
            for i, char in enumerate(sequence_upper):
                if char in CONFUSION_PAIRS:
                    for confused_char in CONFUSION_PAIRS[char]:
                        # Generate alternative sequence
                        alt_seq = list(sequence_upper)
                        alt_seq[i] = confused_char
                        alternatives.append({
                            "original": sequence_upper,
                            "alternative": ''.join(alt_seq),
                            "position": i,
                            "confused_pair": f"{char}↔{confused_char}",
                            "confidence": 0.8  # High confidence for known confusions
                        })
            
            result = {
                "original_sequence": letter_sequence,
                "num_alternatives": len(alternatives),
                "alternatives": alternatives[:10],  # Top 10 most likely
                "has_known_confusions": len(alternatives) > 0
            }
            
            logger.info(f"🔄 Confusion analysis: '{letter_sequence}' → {len(alternatives)} alternatives")
            return result
        
        return analyze_confusions
    
    def _create_buffer_inspection_tool(self):
        """
        Tool that inspects current word buffer state from Redis.
        """
        def inspect_buffer(session_id: str) -> Dict[str, Any]:
            """
            Inspect the current word buffer and sliding window for a session.
            
            Args:
                session_id: The session to inspect
            
            Returns:
                Dictionary with buffer state and window statistics
            """
            try:
                # Get word buffer
                buffer = self.redis_manager.get_word_buffer(session_id, session_id)
                
                # Get sliding window
                window = self.redis_manager.get_window(session_id)
                
                result = {
                    "session_id": session_id,
                    "current_word": buffer.current_word,
                    "num_letters": len(buffer.letters),
                    "letters": buffer.letters,
                    "last_commit_time": buffer.last_commit_time,
                    "window_size": len(window),
                    "window_letters": [entry.char for entry in window],
                    "window_confidences": [entry.confidence for entry in window]
                }
                
                logger.debug(f"🔍 Buffer inspection: {session_id} → '{buffer.current_word}'")
                return result
            
            except Exception as e:
                logger.error(f"Error inspecting buffer: {e}")
                return {"error": str(e)}
        
        return inspect_buffer
    
    def resolve_word_with_agent(
        self,
        session_id: str,
        user_id: str,
        raw_word: str
    ) -> ResolvedWord:
        """
        Use Strands Agent to intelligently resolve a fingerspelled word.
        
        Args:
            session_id: Current session identifier
            user_id: User identifier for personalized lexicon
            raw_word: Raw letter sequence from commit engine
        
        Returns:
            ResolvedWord with top 5 candidates ranked by hybrid score
        """
        logger.info(f"🤖 Agent resolving: '{raw_word}' (session: {session_id})")
        
        # Construct agent prompt
        prompt = f"""I have received the fingerspelled letter sequence: "{raw_word}"

Please help me resolve this to actual words from my personalized lexicon.

Steps:
1. Analyze potential ASL character confusions in this sequence
2. Generate likely alternative sequences accounting for common confusions
3. Search my lexicon for the original sequence
4. Search my lexicon for the most promising alternatives
5. Return the top 5 most confident word matches

Focus on words that:
- Exist in my personalized vocabulary
- Account for known ASL confusions (W↔6, A↔E, etc.)
- Match the semantic context of my usage patterns
"""
        
        try:
            # Invoke agent synchronously
            result = self.agent(prompt)
            
            # Extract resolved words from agent result
            # In practice, you'd parse the agent's structured output
            # For now, we fall back to word_resolver for actual resolution
            
            logger.info(f"🤖 Agent result: {result.messages[-1].content[:200]}")
            
            # Fall back to word resolver for actual MongoDB query
            buffer = WordBuffer(
                session_id=session_id,
                user_id=user_id,
                letters=list(raw_word)
            )
            
            resolved = self.word_resolver.resolve_word(buffer, search_method="fuzzy")
            
            logger.info(f"✓ Agent resolved '{raw_word}' → {len(resolved.all_results)} results")
            return resolved
        
        except Exception as e:
            logger.error(f"Error in agent resolution: {e}")
            
            # Fall back to word resolver
            buffer = WordBuffer(
                session_id=session_id,
                user_id=user_id,
                letters=list(raw_word)
            )
            return self.word_resolver.resolve_word(buffer, search_method="fuzzy")
    
    async def resolve_word_with_agent_async(
        self,
        session_id: str,
        user_id: str,
        raw_word: str
    ) -> ResolvedWord:
        """
        Async version using Strands stream_async for real-time event streaming.
        
        Args:
            session_id: Current session identifier
            user_id: User identifier for personalized lexicon
            raw_word: Raw letter sequence from commit engine
        
        Returns:
            ResolvedWord with top 5 candidates ranked by hybrid score
        """
        logger.info(f"🤖 Agent resolving (async): '{raw_word}' (session: {session_id})")
        
        prompt = f"""Resolve fingerspelled sequence: "{raw_word}"

Analyze confusions, search lexicon, return top 5 matches."""
        
        try:
            # Stream agent execution asynchronously
            agent_output = []
            
            async for event in self.agent.stream_async(prompt):
                # Track lifecycle
                if event.get("init_event_loop"):
                    logger.debug("🔄 Agent event loop initialized")
                
                # Track tool usage
                if "current_tool_use" in event:
                    tool_name = event["current_tool_use"].get("name")
                    if tool_name:
                        logger.info(f"🔧 Agent using: {tool_name}")
                
                # Collect output data
                if "data" in event:
                    agent_output.append(event["data"])
                
                # Track reasoning
                if event.get("reasoning"):
                    reasoning = event.get("reasoningText", "")
                    if reasoning:
                        logger.debug(f"🧠 Reasoning: {reasoning[:80]}")
                
                # Final result
                if "result" in event:
                    logger.info("✅ Agent completed reasoning")
            
            # Join agent output
            full_output = "".join(agent_output)
            logger.debug(f"🤖 Agent output: {full_output[:200]}")
            
            # Parse agent's recommendations and query MongoDB
            buffer = WordBuffer(
                session_id=session_id,
                user_id=user_id,
                letters=list(raw_word)
            )
            
            resolved = self.word_resolver.resolve_word(buffer, search_method="fuzzy")
            
            logger.info(f"✓ Agent resolved (async) '{raw_word}' → {len(resolved.all_results)} results")
            return resolved
        
        except Exception as e:
            logger.error(f"Error in async agent resolution: {e}")
            
            # Fall back to word resolver
            buffer = WordBuffer(
                session_id=session_id,
                user_id=user_id,
                letters=list(raw_word)
            )
            return self.word_resolver.resolve_word(buffer, search_method="fuzzy")
    
    def process_letter_stream_with_agent(
        self,
        session_id: str,
        user_id: str,
        letter_prediction: LetterPrediction
    ) -> Optional[ResolvedWord]:
        """
        Process incoming letter prediction through commit engine and agent.
        
        This is the main entry point for the agent-powered pipeline.
        
        Args:
            session_id: Current session
            user_id: User identifier
            letter_prediction: Letter prediction from model service
        
        Returns:
            ResolvedWord if word was finalized, None if still accumulating
        """
        # Handle skip events (pause detection)
        if letter_prediction.event_type == 'skip':
            logger.debug(f"Skip event: {letter_prediction.skip_reason}")
            
            if self.commit_engine.check_pause(session_id):
                # Word finalization triggered by pause
                buffer = self.redis_manager.get_word_buffer(session_id, user_id)
                
                if buffer.letters:
                    raw_word = buffer.current_word
                    logger.info(f"⏸️  Pause detected → finalizing '{raw_word}'")
                    
                    # Use agent to resolve
                    resolved = self.resolve_word_with_agent(session_id, user_id, raw_word)
                    
                    # Clean up session state
                    self.redis_manager.clear_word_buffer(session_id)
                    self.redis_manager.clear_window(session_id)
                    
                    return resolved
            
            return None
        
        # Handle letter prediction
        if letter_prediction.event_type == 'prediction' and letter_prediction.prediction:
            char = letter_prediction.prediction
            confidence = letter_prediction.confidence or 0.0
            timestamp = datetime.now().timestamp()
            
            # Process through commit engine
            buffer = self.commit_engine.process_letter(
                session_id=session_id,
                user_id=user_id,
                char=char,
                confidence=confidence,
                timestamp=timestamp
            )
            
            # Check for pause after processing
            if self.commit_engine.check_pause(session_id):
                raw_word = buffer.current_word
                
                if raw_word:
                    logger.info(f"⏸️  Pause detected → finalizing '{raw_word}'")
                    
                    # Use agent to resolve
                    resolved = self.resolve_word_with_agent(session_id, user_id, raw_word)
                    
                    # Clean up session state
                    self.redis_manager.clear_word_buffer(session_id)
                    self.redis_manager.clear_window(session_id)
                    
                    return resolved
        
        return None
    
    def close(self):
        """Cleanup agent resources"""
        logger.info("Closing Fingerspelling Agent")
        # Strands Agent handles its own cleanup

