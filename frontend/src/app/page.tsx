"use client";

import React, { useState, useRef, useEffect } from "react";
import { Swiper, SwiperSlide } from "swiper/react";
import { EffectCoverflow, Pagination, Autoplay } from "swiper/modules";
import type { Swiper as SwiperCore } from "swiper";
import { motion, AnimatePresence } from "framer-motion";
import "swiper/css";
import "swiper/css/effect-coverflow";
import "swiper/css/pagination";

import PhotoUploadModal from "../components/photoUpload";
import VoiceInterface from "../components/voiceInterface";
import { voiceService, type VoiceQueryResult } from "../services/voiceService";

const TypewriterText = ({
  text,
  onComplete,
  className,
}: {
  text: string;
  onComplete?: () => void;
  className?: string;
}) => {
  const [displayedText, setDisplayedText] = useState("");

  useEffect(() => {
    let currentText = "";
    setDisplayedText("");
    const words = text.split(" ");
    let currentWordIndex = 0;
    const intervalId = setInterval(() => {
      if (currentWordIndex < words.length) {
        currentText =
          currentText +
          (currentWordIndex > 0 ? " " : "") +
          words[currentWordIndex];
        setDisplayedText(currentText);
        currentWordIndex++;
      } else {
        clearInterval(intervalId);
        if (onComplete) onComplete();
      }
    }, 120);
    return () => clearInterval(intervalId);
  }, [text, onComplete]);
  return <p className={className}>{displayedText}</p>;
};

export default function Home() {
  const [view, setView] = useState<"home" | "thinking" | "chat">("home");
  const [conversation, setConversation] = useState<
    { sender: "user" | "agent"; query: string; response?: string }[]
  >([]);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isInitiated, setIsInitiated] = useState(false);
  const carouselRef = useRef<SwiperCore | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);

  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);
  const [showPhotoUploadLeft, setShowPhotoUploadLeft] = useState(false);

  const [currentUserQuery, setCurrentUserQuery] = useState("");
  const [isVoiceListening, setIsVoiceListening] = useState(false);
  const [isProcessingVoice, setIsProcessingVoice] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState("");

  const [actualUserQueries, setActualUserQueries] = useState<string[]>([]);
  const [isUsingRealQueries, setIsUsingRealQueries] = useState(false);

  // NEW: Backend integration state
  const [useBackendTranscription, setUseBackendTranscription] = useState(true); // Toggle for backend vs browser
  const [currentUserId] = useState("user_123"); // You might get this from auth/session
  const [apiEndpoint] = useState("http://localhost:8000/api/process"); // Your API endpoint

  const memoryPhotos = [
    { id: 1, name: "Jennifer Chen", imageUrl: "/Jennifer.jpeg" },
    { id: 2, name: "Jake's Bday", imageUrl: "/Jakes Birthday.jpeg" },
    { id: 3, name: "Coffee Meetup", imageUrl: "/Coffee Meetup.jpeg" },
    { id: 4, name: "Team Lunch", imageUrl: "/Team Lunch.jpeg" },
    { id: 5, name: "Day at Park", imageUrl: "/Day at park.jpeg" },
  ];

  useEffect(() => {
    if (chatContainerRef.current) {
      const { scrollHeight, clientHeight } = chatContainerRef.current;
      chatContainerRef.current.scrollTo({
        top: scrollHeight - clientHeight,
        behavior: "smooth",
      });
    }
  }, [conversation]);

  const wait = (ms: number) => new Promise((res) => setTimeout(res, ms));

  const switchToThinking = () => {
    setView("thinking");
  };

  const handleVoiceTranscript = async (
    transcript: string,
    isFinal: boolean
  ) => {
    console.log(`Voice transcript: "${transcript}", isFinal: ${isFinal}`);

    if (useBackendTranscription) {
      // In backend mode, only update UI for preview (not final processing)
      if (!isFinal && transcript.startsWith("[Preview]")) {
        setCurrentUserQuery(transcript);
        setVoiceTranscript(transcript);
      } else if (isFinal) {
        // This is the final backend transcription
        setCurrentUserQuery(transcript);
        setVoiceTranscript(transcript);

        // Auto-process the backend transcription
        await processVoiceQuery(transcript);
      }
    } else {
      // Browser-only mode (original behavior)
      setCurrentUserQuery(transcript);
      setVoiceTranscript(transcript);

      if (isFinal) {
        await processVoiceQuery(transcript);
      }
    }
  };

  // NEW: Handle backend response
  const handleBackendResponse = async (response: any) => {
    console.log("Backend response received:", response);

    if (response.success && response.result) {
      const { transcribed_text, response: agentResponse } = response.result;

      // The transcript has already been handled in handleVoiceTranscript
      // This is where you can handle additional backend data like:
      // - Audio responses
      // - Intent detection results
      // - Memory storage confirmations

      if (response.result.audio_response) {
        // Play audio response if available
        playAudioResponse(response.result.audio_response);
      }

      // Log for debugging
      console.log("Agent response:", agentResponse);
      console.log("Transcribed text:", transcribed_text);
    }
  };

  // NEW: Play audio response from backend
  const playAudioResponse = (audioData: string) => {
    try {
      const audio = new Audio(`data:audio/mp3;base64,${audioData}`);
      audio.play().catch(console.error);
    } catch (error) {
      console.error("Error playing audio response:", error);
    }
  };

  const handleVoiceStart = () => {
    setCurrentUserQuery("");
    setVoiceTranscript("");
    console.log("Voice input started");
  };

  const handleVoiceEnd = () => {
    console.log("Voice input ended");
  };

  const handleVoiceError = (error: string) => {
    console.error("Voice error:", error);
    setIsVoiceListening(false);
    setIsProcessingVoice(false);
    // Show error to user
    setCurrentUserQuery(`Voice Error: ${error}`);

    // Clear error after 3 seconds
    setTimeout(() => {
      setCurrentUserQuery("");
    }, 3000);
  };

  const toggleVoiceListening = async () => {
    if (isProcessingVoice) return;

    if (isVoiceListening) {
      // Stop listening
      setIsVoiceListening(false);

      // If using browser-only transcription, process the current transcript
      if (!useBackendTranscription && voiceTranscript.trim()) {
        setIsProcessingVoice(true);
        await processVoiceQuery(voiceTranscript);
        setIsProcessingVoice(false);
      }
      // Note: Backend transcription will be handled automatically in handleVoiceTranscript
    } else {
      // Start listening
      setIsVoiceListening(true);
    }

    //   if (voiceTranscript.trim()) {
    //     setIsProcessingVoice(true);

    //     try {
    //       const result: VoiceQueryResult = await voiceService.processVoiceQuery(
    //         voiceTranscript
    //       );

    //       let adjustedResponse = result.response;

    //       // SPECIAL OVERRIDE for Jake's Bday
    //       if (
    //         voiceTranscript.toLowerCase().includes("jake") &&
    //         voiceTranscript.toLowerCase().includes("bday")
    //       ) {
    //         adjustedResponse = "I'm here! What's happening right now?";
    //       }

    //       if (result.success && adjustedResponse) {
    //         if (
    //           voiceTranscript
    //             .toLowerCase()
    //             .includes("i want to remember this moment")
    //         ) {
    //           setShowPhotoUploadLeft(true);
    //         }
    //         await handleVoiceQuery(voiceTranscript, adjustedResponse);
    //       } else {
    //         setCurrentUserQuery(
    //           "I'm sorry, I couldn't process your request. Please try again."
    //         );
    //       }
    //     } catch (error) {
    //       console.error("Error processing voice query:", error);
    //       setCurrentUserQuery(
    //         "I'm experiencing some technical difficulties. Please try again."
    //       );
    //     } finally {
    //       setIsProcessingVoice(false);
    //     }
    //   }
    // } else {
    //   setIsVoiceListening(true);
    // }
  };

  // Modified to handle both backend and legacy voiceService
  const processVoiceQuery = async (transcript: string) => {
    if (!transcript.trim()) return;

    setIsProcessingVoice(true);

    try {
      let response: string;

      if (useBackendTranscription) {
        // Backend has already processed and returned the response in handleBackendResponse
        // For now, we'll use a default response since the actual response should come from backend
        response =
          "I've received and processed your message through the backend.";

        // SPECIAL OVERRIDE for Jake's Bday (keeping your existing logic)
        if (
          transcript.toLowerCase().includes("jake") &&
          transcript.toLowerCase().includes("bday")
        ) {
          response = "I'm here! What's happening right now?";
        }
      } else {
        // Use legacy voiceService for browser-only mode
        const result: VoiceQueryResult = await voiceService.processVoiceQuery(
          transcript
        );

        if (result.success && result.response) {
          response = result.response;

          // SPECIAL OVERRIDE for Jake's Bday
          if (
            transcript.toLowerCase().includes("jake") &&
            transcript.toLowerCase().includes("bday")
          ) {
            response = "I'm here! What's happening right now?";
          }
        } else {
          response =
            "I'm sorry, I couldn't process your request. Please try again.";
        }
      }

      // Handle memory upload trigger
      if (transcript.toLowerCase().includes("i want to remember this moment")) {
        setShowPhotoUploadLeft(true);
      }

      // Process the conversation flow
      await handleVoiceQuery(transcript, response);
    } catch (error) {
      console.error("Error processing voice query:", error);
      setCurrentUserQuery(
        "I'm experiencing some technical difficulties. Please try again."
      );
    } finally {
      setIsProcessingVoice(false);
    }
  };

  const handleVoiceQuery = async (query: string, response: string) => {
    if (view === "home") {
      setIsInitiated(true);
      setIsUsingRealQueries(true);
      setActualUserQueries([query]);
      if (carouselRef.current) carouselRef.current.autoplay.stop();

      setView("thinking");
      await wait(2000);

      setConversation([{ sender: "user", query: query }]);
      setView("chat");

      const words = query.split(" ");
      const typewriterDuration = words.length * 120 + 500;
      await wait(typewriterDuration);

      setConversation((prev) => [
        ...prev,
        { sender: "agent", query: "", response: response },
      ]);
      setCurrentStepIndex(1);
    } else if (view === "chat") {
      const newQueryIndex = actualUserQueries.length;
      setActualUserQueries((prev) => [...prev, query]);
      setConversation((prev) => [...prev, { sender: "user", query: query }]);

      const words = query.split(" ");
      const typewriterDuration = words.length * 120 + 500;
      await wait(typewriterDuration);

      setConversation((prev) => [
        ...prev,
        { sender: "agent", query: "", response: response },
      ]);
      setCurrentStepIndex((prev) => prev + 1);
    }
  };

  const handleGoHome = () => {
    setView("home");
    setConversation([]);
    setCurrentStepIndex(0);
    setIsInitiated(false);
    setIsUsingRealQueries(false);
    setActualUserQueries([]);
    setCurrentUserQuery("");
    setVoiceTranscript("");
    setIsVoiceListening(false);
    setIsProcessingVoice(false);
    setShowPhotoUploadLeft(false);
    voiceService.resetConversation();
    if (carouselRef.current) {
      carouselRef.current.autoplay?.start();
    }
  };

  // NEW: Toggle between backend and browser transcription
  const toggleTranscriptionMode = () => {
    setUseBackendTranscription(!useBackendTranscription);
    console.log(
      `Switched to ${
        !useBackendTranscription ? "backend" : "browser"
      } transcription`
    );
  };

  return (
    <div className="bg-gray-50 text-gray-800 min-h-screen font-sans overflow-hidden relative">
      {/* This div blurs the background when the modal is open */}
      <div
        className={`transition-all duration-300 ${
          isPhotoModalOpen ? "blur-sm" : ""
        }`}
      >
        <AnimatePresence>
          {view === "home" && (
            <motion.div
              initial={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              className="absolute inset-0"
            >
              <div className="bg-black">
                <header className="flex justify-between items-center p-5 max-w-5xl mx-auto">
                  <div className="text-2xl font-bold text-white">
                    Life Witness
                  </div>
                  <nav className="flex gap-4 sm:gap-6 text-white">
                    <a href="/our-project" className="hover:text-gray-300">
                      Our Project
                    </a>
                    <a href="/meet-your-agents" className="hover:text-gray-300">
                      Meet Your Agents
                    </a>
                    <a href="/settings" className="hover:text-gray-300">
                      Settings
                    </a>
                    {/* NEW: Toggle button for transcription mode */}
                    <button
                      onClick={toggleTranscriptionMode}
                      className="bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded text-sm"
                      title={`Currently using ${
                        useBackendTranscription ? "backend" : "browser"
                      } transcription`}
                    >
                      {useBackendTranscription ? "🔧 Backend" : "🌐 Browser"}
                    </button>
                  </nav>
                </header>
              </div>
              <div className="p-5 sm:p-8 flex flex-col h-full max-w-5xl mx-auto">
                <main className="flex-grow flex flex-col items-center justify-center space-y-10">
                  <div className="text-center">
                    <h1 className="text-5xl font-bold text-gray-800">
                      <span className="bg-gradient-to-r from-amber-500 to-orange-500 bg-clip-text text-transparent">
                        Hello,
                      </span>{" "}
                      what memory
                    </h1>
                    <h1 className="text-5xl font-bold text-gray-800 mt-2">
                      would you like to inquire about today?
                    </h1>
                  </div>
                  <Swiper
                    onSwiper={(swiper) => {
                      carouselRef.current = swiper;
                    }}
                    onSlideChange={(swiper) => setActiveIndex(swiper.realIndex)}
                    effect={"coverflow"}
                    grabCursor={true}
                    centeredSlides={true}
                    slidesPerView={3}
                    loop={true}
                    autoplay={{ delay: 3000, disableOnInteraction: false }}
                    modules={[EffectCoverflow, Pagination, Autoplay]}
                    className="w-full"
                    coverflowEffect={{
                      rotate: 0,
                      stretch: 80,
                      depth: 150,
                      modifier: 1,
                      slideShadows: false,
                    }}
                  >
                    {memoryPhotos.map((photo, index) => (
                      <SwiperSlide key={photo.id}>
                        <div className="flex flex-col items-center justify-center h-full pt-10">
                          <img
                            src={photo.imageUrl}
                            alt={photo.name || ""}
                            className={`w-32 h-32 sm:w-40 sm:h-40 object-cover rounded-2xl shadow-lg transition-all duration-300 ${
                              activeIndex === index
                                ? "scale-110 shadow-2xl"
                                : "scale-90 opacity-60"
                            }`}
                          />
                          <span
                            className={`block mt-4 font-medium text-sm transition-opacity duration-300 ${
                              activeIndex === index
                                ? "opacity-100"
                                : "opacity-60"
                            }`}
                          >
                            {photo.name}
                          </span>
                        </div>
                      </SwiperSlide>
                    ))}
                  </Swiper>
                  <div className="w-full max-w-3xl bg-white p-2 rounded-full border border-gray-200 shadow-sm flex items-center h-20">
                    <div className="flex-grow px-4">
                      {isInitiated ? (
                        <TypewriterText
                          text={actualUserQueries[0] || ""}
                          onComplete={switchToThinking}
                          className="text-gray-800 text-base"
                        />
                      ) : (
                        <p className="text-gray-500 text-base">
                          {isProcessingVoice
                            ? "Processing your request..."
                            : isVoiceListening && voiceTranscript
                            ? voiceTranscript
                            : currentUserQuery ||
                              "Ask or talk about a memory..."}
                        </p>
                      )}
                    </div>
                    {/* UPDATED: Use controlled VoiceInterface */}
                    <VoiceInterface
                      onTranscript={handleVoiceTranscript}
                      onVoiceStart={handleVoiceStart}
                      onVoiceEnd={handleVoiceEnd}
                      onError={handleVoiceError}
                      disabled={isProcessingVoice}
                      isListening={isVoiceListening}
                      onToggleListening={toggleVoiceListening}
                      // NEW props for backend integration
                      useBackendTranscription={useBackendTranscription}
                      onBackendResponse={handleBackendResponse}
                      userId={currentUserId}
                      apiEndpoint={apiEndpoint}
                    />
                    {/* --- PARTNER'S ADDITION: onClick handler for the upload button --- */}
                    <button
                      onClick={() => setIsPhotoModalOpen(true)}
                      className="bg-blue-500 hover:bg-blue-600 text-white rounded-full py-3 px-6 font-semibold text-sm"
                    >
                      Upload Memory
                    </button>
                  </div>
                </main>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {view === "thinking" && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex flex-col items-center justify-center bg-white"
            >
              <p className="text-lg mb-4">"{actualUserQueries[0] || ""}"</p>
              <div className="flex items-center justify-center gap-2">
                <motion.span
                  animate={{ y: [0, -10, 0] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    ease: "easeInOut",
                  }}
                  className="w-3 h-3 bg-blue-500 rounded-full"
                />
                <motion.span
                  animate={{ y: [0, -10, 0] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: 0.2,
                  }}
                  className="w-3 h-3 bg-blue-500 rounded-full"
                />
                <motion.span
                  animate={{ y: [0, -10, 0] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: 0.4,
                  }}
                  className="w-3 h-3 bg-blue-500 rounded-full"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {view === "chat" && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5 }}
              className="absolute inset-0"
            >
              <div className="flex h-screen">
                {/* Left Panel */}
                <div className="w-1/3 bg-gray-50 border-r border-gray-200 p-8 flex flex-col justify-center items-center relative">
                  <button
                    onClick={handleGoHome}
                    className="absolute top-6 left-6 text-2xl hover:text-gray-500"
                  >
                    &times;
                  </button>
                  {/* NEW: Mode indicator */}
                  <div className="absolute top-6 right-6 text-sm text-gray-500">
                    {useBackendTranscription ? "🔧" : "🌐"}
                  </div>
                  <div className="w-full">
                    {showPhotoUploadLeft ? (
                      <div className="flex flex-col items-start w-full">
                        <PhotoUploadModal
                          isOpen={true}
                          onClose={() => {}}
                          onPhotoUpload={(photo) =>
                            console.log(
                              "Photo uploaded during memory creation:",
                              photo
                            )
                          }
                        />
                      </div>
                    ) : (
                      <div className="flex flex-col items-center w-full">
                        <img
                          src="/Jennifer.jpeg"
                          alt="Jennifer Chen"
                          className="w-40 h-40 object-cover rounded-xl shadow-xl"
                        />
                        <p className="mt-4 text-lg font-semibold text-center">
                          Jennifer Chen
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Right Panel */}
                <div className="w-2/3 flex flex-col p-8 bg-white">
                  <div
                    ref={chatContainerRef}
                    className="flex-grow overflow-y-auto pr-4 space-y-6"
                  >
                    {conversation.map((chat, index) => (
                      <div key={index}>
                        {chat.sender === "user" ? (
                          <div className="flex items-start gap-3 justify-end">
                            <div className="bg-blue-500 text-white p-3 rounded-lg max-w-xl">
                              <TypewriterText text={chat.query} />
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-start gap-3">
                            <div className="bg-gray-100 p-3 rounded-lg max-w-xl">
                              <TypewriterText text={chat.response || ""} />
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Chat input area */}
                  <div className="flex-shrink-0 pt-6">
                    {/* Voice interface */}
                    <div className="flex justify-center">
                      <VoiceInterface
                        onTranscript={handleVoiceTranscript}
                        onVoiceStart={handleVoiceStart}
                        onVoiceEnd={handleVoiceEnd}
                        onError={handleVoiceError}
                        disabled={isProcessingVoice}
                        isListening={isVoiceListening}
                        onToggleListening={toggleVoiceListening}
                        // NEW: Backend integration props for chat view too
                        useBackendTranscription={useBackendTranscription}
                        onBackendResponse={handleBackendResponse}
                        userId={currentUserId}
                        apiEndpoint={apiEndpoint}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* SHIVANI ADDITION: The modal component itself */}
      <PhotoUploadModal
        isOpen={isPhotoModalOpen}
        onClose={() => setIsPhotoModalOpen(false)}
        onPhotoUpload={(photo) => {
          // This is where you'd handle the uploaded photo data
          console.log("New photo uploaded:", photo);
          setIsPhotoModalOpen(false); // Close modal after upload
        }}
      />
    </div>
  );
}
