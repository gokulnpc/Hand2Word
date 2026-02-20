"use client";
import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

// Import the two apps you just refactored
import TrainingGame from "@/components/demo/TrainingGame";
import AutocorrectApp from "@/components/demo/AutocorrectApp";

// You can reuse your existing Tabs component for navigation
import Tabs from "@/components/autocorrect/Tabs";
import Link from "next/link"; // Assuming Next.js for client-side navigation

type View = "Training" | "Autocorrect" | "Home"; // Added 'Home' view

export default function DemoHubPage() {
  const [view, setView] = useState<View>("Home");

  // Variant for the fade-in-up animation on cards/text
  const fadeInUp = {
    initial: { y: 20, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    transition: { duration: 0.6, ease: [0.6, -0.05, 0.01, 0.99] },
  };

  const stagger = {
    animate: {
      transition: {
        staggerChildren: 0.1,
      },
    },
  };

  // Render the Home page or the selected app
  const renderContent = () => {
    if (view === "Home") {
      return (
        <motion.div
          key="home"
          initial="initial"
          animate="animate"
          exit={{ opacity: 0, y: -20 }}
          variants={stagger}
          className="flex flex-col items-center justify-center min-h-[calc(100vh-180px)] text-center px-4" // Adjusted min-h to account for header
        >
          {/* Hero Section */}
          <motion.h1
            variants={fadeInUp}
            className="text-5xl md:text-6xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-fuchsia-600 drop-shadow-lg"
          >
            Master ASL. Elevate Your Fluency.
          </motion.h1>
          <motion.p
            variants={fadeInUp}
            className="mt-4 text-xl md:text-2xl text-white/70 max-w-3xl leading-relaxed"
          >
            Dive into interactive fingerspelling training or get real-time
            autocorrection for precision. Your ASL journey starts here.
          </motion.p>

          {/* Feature Cards */}
          <motion.div
            variants={stagger}
            className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-4xl"
          >
            <motion.div
              variants={fadeInUp}
              whileHover={{
                scale: 1.03,
                boxShadow: "0 10px 20px rgba(0,0,0,0.3)",
              }}
              onClick={() => setView("Training")}
              className="group cursor-pointer rounded-3xl p-8 bg-gradient-to-br from-indigo-800/40 to-purple-800/40 border border-indigo-700/50 shadow-2xl backdrop-blur-md transition-all duration-300 relative overflow-hidden"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/20 to-fuchsia-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              <h3 className="relative z-10 text-3xl font-bold text-white mb-3">
                ASL Training Game
              </h3>
              <p className="relative z-10 text-white/70 text-lg">
                Practice fingerspelling with AI-powered coaching tips. Improve
                your form and speed.
              </p>
              <span className="relative z-10 mt-6 inline-block px-6 py-2 rounded-full bg-white text-black font-bold text-md group-hover:bg-gradient-to-r group-hover:from-fuchsia-400 group-hover:to-orange-400 transition-all duration-300">
                Start Training →
              </span>
            </motion.div>

            <motion.div
              variants={fadeInUp}
              whileHover={{
                scale: 1.03,
                boxShadow: "0 10px 20px rgba(0,0,0,0.3)",
              }}
              onClick={() => setView("Autocorrect")}
              className="group cursor-pointer rounded-3xl p-8 bg-gradient-to-br from-teal-800/40 to-blue-800/40 border border-teal-700/50 shadow-2xl backdrop-blur-md transition-all duration-300 relative overflow-hidden"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-teal-500/20 to-blue-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              <h3 className="relative z-10 text-3xl font-bold text-white mb-3">
                ASL Autocorrect Agent
              </h3>
              <p className="relative z-10 text-white/70 text-lg">
                Get real-time word suggestions as you fingerspell. Enhance
                accuracy and clarity.
              </p>
              <span className="relative z-10 mt-6 inline-block px-6 py-2 rounded-full bg-white text-black font-bold text-md group-hover:bg-gradient-to-r group-hover:from-blue-400 group-hover:to-green-400 transition-all duration-300">
                Use Autocorrect →
              </span>
            </motion.div>
          </motion.div>
        </motion.div>
      );
    } else if (view === "Training") {
      return <TrainingGame />;
    } else {
      return <AutocorrectApp />;
    }
  };

  return (
    <main className="min-h-screen w-full bg-neutral-950 text-white relative overflow-hidden">
      {/* Background Gradient Effect */}
      <div className="absolute inset-0 -z-10 opacity-30">
        <div className="absolute top-0 left-0 w-80 h-80 bg-fuchsia-500 rounded-full mix-blend-multiply filter blur-xl opacity-70 animate-blob"></div>
        <div className="absolute top-0 -right-20 w-80 h-80 bg-purple-500 rounded-full mix-blend-multiply filter blur-xl opacity-70 animate-blob animation-delay-2000"></div>
        <div className="absolute -bottom-8 left-20 w-80 h-80 bg-blue-500 rounded-full mix-blend-multiply filter blur-xl opacity-70 animate-blob animation-delay-4000"></div>
      </div>
      {/* End Background Gradient Effect */}

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-8 relative z-10">
        {/* HEADER: Updated with the project name "Glossa" and a logo placeholder */}
        <header className="flex flex-col md:flex-row items-center justify-between gap-6 border-b border-white/10 pb-6">
          <Link
            href="#"
            onClick={() => setView("Home")}
            className="flex items-center gap-3 group"
          >
            {" "}
            {/* Added 'items-center' and 'gap-3' for spacing */}
            {/* Logo Placeholder - This is where your actual SVG or image logo would go */}
            <div className="w-8 h-8 md:w-10 md:h-10 bg-gradient-to-r from-blue-400 to-fuchsia-600 rounded-full flex items-center justify-center text-xl font-bold text-white/90 group-hover:from-fuchsia-400 group-hover:to-orange-400 transition-all duration-300">
              G {/* Simple 'G' for now, replaced by your actual logo */}
            </div>
            <div className="flex flex-col items-center md:items-start text-center md:text-left">
              <h1 className="text-3xl font-bold tracking-tight text-white group-hover:text-blue-400 transition-colors">
                Glossa
              </h1>
              <p className="text-sm text-white/60 mt-1">
                Made with ❤️ for Hack Midwest
              </p>
            </div>
          </Link>
          {view !== "Home" && (
            <Tabs
              tabs={["Training", "Autocorrect"]}
              current={view}
              onChange={(t) => setView(t as any)}
            />
          )}
        </header>

        {/* ANIMATED CONTENT AREA */}
        <AnimatePresence mode="wait">
          <motion.div
            key={view} // The key is crucial for AnimatePresence to detect changes
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
          >
            {renderContent()}
          </motion.div>
        </AnimatePresence>
      </div>
    </main>
  );
}
