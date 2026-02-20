"""Word Resolver - Fuzzy search integration with MongoDB Atlas"""
import logging
from typing import Optional, List, Dict, Any
from pymongo import MongoClient
from config import settings
from models import ResolvedWord, WordBuffer, SearchResult

logger = logging.getLogger(__name__)


class WordResolver:
    """
    Resolves fingerspelled words using MongoDB Atlas fuzzy search.
    Two modes:
    1. Default: Fuzzy search (fast, most cases)
    2. Long pause / skip events: Full fuzzy search over surface + aliases
    """
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db = None
        self.collection = None
        self._init_mongo()
    
    def _init_mongo(self):
        """Initialize MongoDB connection"""
        if not settings.mongodb_url:
            logger.warning("⚠️  MONGODB_URL not configured, word resolution will be disabled")
            return
        
        try:
            self.client = MongoClient(
                settings.mongodb_url,
                tls=True,
                tlsAllowInvalidCertificates=False,
                serverSelectionTimeoutMS=5000
            )
            self.db = self.client[settings.mongodb_db]
            self.collection = self.db[settings.mongodb_collection]
            
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"✓ Connected to MongoDB Atlas ({settings.mongodb_db}.{settings.mongodb_collection})")
        
        except Exception as e:
            logger.error(f"✗ Failed to connect to MongoDB: {e}")
            self.client = None
    
    def resolve_word(
        self,
        buffer: WordBuffer,
        search_method: str = "fuzzy"
    ) -> ResolvedWord:
        """
        Resolve a word buffer using fuzzy search.
        
        Args:
            buffer: WordBuffer with committed letters
            search_method: 'fuzzy' (default) or 'skip_event' (full search)
        
        Returns:
            ResolvedWord with resolution results
        """
        raw_word = buffer.current_word
        
        if not raw_word:
            logger.warning(f"Empty word for session {buffer.session_id}")
            return ResolvedWord(
                session_id=buffer.session_id,
                user_id=buffer.user_id,
                raw_word="",
                search_method=search_method
            )
        
        logger.info(f"🔍 Resolving word: '{raw_word}' ({buffer.session_id}, method: {search_method})")
        
        if self.collection is None:
            logger.warning("MongoDB not available, returning raw word")
            return ResolvedWord(
                session_id=buffer.session_id,
                user_id=buffer.user_id,
                raw_word=raw_word,
                search_method=search_method
            )
        
        try:
            # Perform Atlas Search with fuzzy matching
            results = self._atlas_fuzzy_search(raw_word, buffer.user_id)
            logger.debug(f"MongoDB Atlas search returned {len(results)} result(s) for '{raw_word}'")
            
            if results:
                # Convert all results to SearchResult objects with hybrid scoring
                all_search_results = []
                for result in results:
                    atlas_score = result.get('score', 0.0)
                    alias_confidence = self._get_alias_confidence(raw_word, result)
                    hybrid_score = (atlas_score * 0.7) + (alias_confidence * 0.3)
                    
                    all_search_results.append(SearchResult(
                        surface=result['surface'],
                        atlas_score=atlas_score,
                        alias_confidence=alias_confidence,
                        hybrid_score=hybrid_score,
                        matched_via=result.get('matched_alias')
                    ))
                
                # Sort by hybrid score (descending)
                all_search_results.sort(key=lambda x: x.hybrid_score, reverse=True)
                
                resolved = ResolvedWord(
                    session_id=buffer.session_id,
                    user_id=buffer.user_id,
                    raw_word=raw_word,
                    all_results=all_search_results,
                    search_method=search_method
                )
                
                logger.info(f"✓ Resolved '{raw_word}' with {len(all_search_results)} result(s)")
                logger.info(f"   Top 5 results:")
                for i, r in enumerate(all_search_results[:5], 1):
                    logger.info(
                        f"     {i}. {r.surface:20} (atlas: {r.atlas_score:.3f}, "
                        f"alias_conf: {r.alias_confidence:.3f}, hybrid: {r.hybrid_score:.3f})"
                    )
                
                return resolved
            
            else:
                logger.info(f"❌ No results for '{raw_word}'")
                return ResolvedWord(
                    session_id=buffer.session_id,
                    user_id=buffer.user_id,
                    raw_word=raw_word,
                    search_method=search_method
                )
        
        except Exception as e:
            logger.error(f"Error resolving word '{raw_word}': {e}")
            return ResolvedWord(
                session_id=buffer.session_id,
                user_id=buffer.user_id,
                raw_word=raw_word,
                search_method=search_method
            )
    
    def _atlas_fuzzy_search(self, query: str, user_id: str) -> List[Dict[str, Any]]:
        # Adaptive strategy: use autocomplete for short queries, fuzzy for longer
        use_autocomplete = len(query) <= 3
        
        if use_autocomplete:
            # Autocomplete: good for incomplete words (prefix matching)
            pipeline = [
                {
                    '$search': {
                        'index': settings.atlas_search_index,
                        'compound': {
                            'should': [
                                {
                                    'autocomplete': {
                                        'query': query.lower(),
                                        'path': 'aliases',
                                        'fuzzy': {
                                            'maxEdits': 1,
                                            'prefixLength': 0
                                        }
                                    }
                                },
                                {
                                    'autocomplete': {
                                        'query': query.lower(),
                                        'path': 'surface',
                                        'fuzzy': {
                                            'maxEdits': 1,
                                            'prefixLength': 0
                                        }
                                    }
                                }
                            ]
                        }
                    }
                },
                {
                    '$project': {
                        'surface': 1,
                        'aliases': 1,
                        'confidence_scores': 1,
                        'user_id': 1,
                        'score': {'$meta': 'searchScore'}
                    }
                },
                {
                    '$limit': 20  # Get 20 for client-side re-ranking
                }
            ]
        else:
            # Fuzzy text search: good for complete words with typos
            pipeline = [
                {
                    '$search': {
                        'index': settings.atlas_search_index,
                        'compound': {
                            'must': [
                                {
                                    'text': {
                                        'query': query.lower(),
                                        'path': ['aliases', 'surface'],
                                        'fuzzy': {
                                            'maxEdits': settings.fuzzy_max_edits,
                                            'prefixLength': settings.fuzzy_prefix_length
                                        }
                                    }
                                }
                            ]
                        }
                    }
                },
                {
                    '$project': {
                        'surface': 1,
                        'aliases': 1,
                        'confidence_scores': 1,
                        'user_id': 1,
                        'score': {'$meta': 'searchScore'}
                    }
                },
                {
                    '$limit': 20  # Get 20 for client-side re-ranking
                }
            ]
        
        strategy = "autocomplete" if use_autocomplete else "fuzzy"
        logger.debug(f"Atlas search: query='{query}', strategy={strategy}")
        
        results = list(self.collection.aggregate(pipeline))
        logger.info(f"====== MongoDB Atlas Results ({strategy}): {results}")
        
        # Find which alias matched (for confidence scoring)
        for result in results:
            matched_alias = self._find_best_matching_alias(query, result.get('aliases', []))
            result['matched_alias'] = matched_alias or result.get('surface')
        
        return results
    
    def _find_best_matching_alias(self, query: str, aliases: List[str]) -> Optional[str]:
        """
        Find the best matching alias for the query using fuzzy matching.
        Returns the alias that best matches the query.
        """
        if not aliases:
            return None
        
        query_upper = query.upper().replace(' ', '').replace('-', '')
        best_alias = None
        best_distance = float('inf')
        
        for alias in aliases:
            alias_upper = alias.upper().replace(' ', '').replace('-', '')
            
            # Exact match - return immediately
            if alias_upper == query_upper:
                return alias
            
            # Prefix match (for autocomplete)
            if alias_upper.startswith(query_upper) or query_upper in alias_upper:
                distance = abs(len(alias_upper) - len(query_upper))
                if distance < best_distance:
                    best_distance = distance
                    best_alias = alias
            
            # Edit distance match (for fuzzy)
            else:
                distance = self._levenshtein_distance(alias_upper, query_upper)
                if distance <= 2 and distance < best_distance:
                    best_distance = distance
                    best_alias = alias
        
        return best_alias
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between two strings."""
        if len(s1) > len(s2):
            s1, s2 = s2, s1
        
        distances = range(len(s1) + 1)
        for i2, c2 in enumerate(s2):
            distances_ = [i2 + 1]
            for i1, c1 in enumerate(s1):
                if c1 == c2:
                    distances_.append(distances[i1])
                else:
                    distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
            distances = distances_
        
        return distances[-1]
    
    def _get_alias_confidence(self, raw_word: str, result: Dict[str, Any]) -> float:
        """
        Get alias confidence score from the matched alias.
        Returns 0.0 if no confidence score available.
        """
        # Get alias confidence if matched via alias
        matched_alias = result.get('matched_alias')
        confidence_scores = result.get('confidence_scores', {})
        alias_conf = confidence_scores.get(matched_alias, 0.0)
        
        return alias_conf
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("Closed MongoDB connection")

