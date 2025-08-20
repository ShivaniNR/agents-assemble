import React, { useState, useRef, useEffect } from "react";

interface VoiceInterfaceProps {
  onTranscript: (transcript: string, isFinal: boolean) => void;
  onVoiceStart?: () => void;
  onVoiceEnd?: () => void;
  onError?: (error: string) => void;
  disabled?: boolean;
  isListening: boolean;
  onToggleListening: () => void;
  useBackendTranscription?: boolean;
  onBackendResponse?: (response: any) => void;
  userId?: string;
  apiEndpoint?: string;
}

const VoiceInterface: React.FC<VoiceInterfaceProps> = ({
  onTranscript,
  onVoiceStart,
  onVoiceEnd,
  onError,
  disabled = false,
  isListening,
  onToggleListening,
  useBackendTranscription = false,
  onBackendResponse,
  userId,
  apiEndpoint,
}) => {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isRecognitionActive, setIsRecognitionActive] = useState(false);
  const recognitionRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Initialize speech recognition once
  useEffect(() => {
    if (typeof window !== "undefined") {
      const SpeechRecognition =
        (window as any).webkitSpeechRecognition ||
        (window as any).SpeechRecognition;

      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onstart = () => {
          console.log("Speech recognition started");
          setIsRecognitionActive(true);
          onVoiceStart?.();
        };

        recognition.onresult = (event: any) => {
          console.log("Speech recognition result received");
          let finalTranscript = "";
          let interimTranscript = "";

          for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
              finalTranscript += transcript;
            } else {
              interimTranscript += transcript;
            }
          }

          // Send interim results for live typing
          if (interimTranscript && !useBackendTranscription) {
            onTranscript(interimTranscript, false);
          }

          // Handle final transcript
          if (finalTranscript) {
            console.log("Final transcript:", finalTranscript);
            if (useBackendTranscription) {
              sendToBackend(finalTranscript);
            } else {
              onTranscript(finalTranscript, true);
            }
          }
        };

        recognition.onerror = (event: any) => {
          console.error("Speech recognition error:", event.error);
          setIsRecognitionActive(false);
          onError?.(event.error);
        };

        recognition.onend = () => {
          console.log("Speech recognition ended");
          setIsRecognitionActive(false);
          onVoiceEnd?.();
        };

        recognitionRef.current = recognition;
      } else {
        console.error("Speech recognition not supported");
        onError?.("Speech recognition not supported in this browser");
      }
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state === "recording"
      ) {
        mediaRecorderRef.current.stop();
      }
    };
  }, []);

  // Handle button click
  const handleClick = async () => {
    if (disabled || isProcessing) return;

    console.log("Voice button clicked, current isListening:", isListening);

    if (isListening) {
      // Stop listening
      stopListening();
    } else {
      // Start listening
      await startListening();
    }

    onToggleListening();
  };

  const startListening = async () => {
    console.log("Starting voice input...");
    audioChunksRef.current = [];

    try {
      // Start speech recognition
      if (recognitionRef.current && !isRecognitionActive) {
        console.log("Starting speech recognition");
        recognitionRef.current.start();
      }

      // Start audio recording if using backend
      if (useBackendTranscription) {
        console.log("Starting audio recording for backend");
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
        const mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };

        mediaRecorder.onstart = () => {
          console.log("MediaRecorder started");
        };

        mediaRecorder.onstop = () => {
          console.log("MediaRecorder stopped");
        };

        mediaRecorder.start(100);
        mediaRecorderRef.current = mediaRecorder;
      }
    } catch (error) {
      console.error("Failed to start recording:", error);
      onError?.("Failed to start recording: " + (error as Error).message);
    }
  };

  const stopListening = () => {
    console.log("Stopping voice input...");

    // Stop speech recognition
    if (recognitionRef.current && isRecognitionActive) {
      console.log("Stopping speech recognition");
      recognitionRef.current.stop();
    }

    // Stop audio recording
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state === "recording"
    ) {
      console.log("Stopping audio recording");
      mediaRecorderRef.current.stop();
    }
  };

  // Send audio to backend
  const sendToBackend = async (browserTranscript: string) => {
    if (!useBackendTranscription || !apiEndpoint) {
      onTranscript(browserTranscript, true);
      return;
    }

    console.log("Sending to backend:", browserTranscript);
    setIsProcessing(true);

    try {
      const formData = new FormData();
      formData.append("browser_transcript", browserTranscript);
      formData.append("user_id", userId || "anonymous");
      formData.append("timestamp", new Date().toISOString());
      formData.append("input_method", "voice");
      formData.append("browser_preview", "false");

      console.log("Audio chunks length:", audioChunksRef.current.length);
      if (audioChunksRef.current.length > 0) {
        // Send with audio
        const audioBlob = new Blob(audioChunksRef.current, {
          type: "audio/webm",
        });
        formData.append("audio", audioBlob, "voice.webm");
      }

      console.log("FormData keys:");
      for (let key of formData.keys()) console.log(key);

      const response = await fetch(apiEndpoint, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      console.log("Backend response:", result);

      if (result && result.success) {
        // ✅ FIXED: Only call onBackendResponse, don't call onTranscript separately
        // This prevents triggering processVoiceQuery which has conflicting logic
        onBackendResponse?.(result);
      } else {
        console.log(
          "Backend request failed, using browser transcript as fallback"
        );
        onTranscript(browserTranscript, true);
      }
    } catch (error) {
      console.error("Backend transcription failed:", error);
      onTranscript(browserTranscript, true);
      onError?.("Backend processing failed, using browser transcription");
    } finally {
      setIsProcessing(false);
      audioChunksRef.current = [];
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={disabled || isProcessing}
      className={`
        relative w-12 h-12 rounded-full flex items-center justify-center transition-all
        ${
          isListening
            ? "bg-red-500 hover:bg-red-600"
            : "bg-blue-500 hover:bg-blue-600"
        }
        ${isListening ? "animate-pulse" : ""}
        ${
          disabled || isProcessing
            ? "opacity-50 cursor-not-allowed"
            : "cursor-pointer"
        }
      `}
      title={isListening ? "Stop recording" : "Start recording"}
    >
      {isProcessing ? (
        <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
      ) : (
        <span className="text-white text-lg">{isListening ? "🔴" : "🎤"}</span>
      )}
    </button>
  );
};

export default VoiceInterface;
