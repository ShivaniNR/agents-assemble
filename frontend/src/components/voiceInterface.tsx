"use client";

import React, { useState, useRef, useEffect } from "react";

interface VoiceInterfaceProps {
  onTranscript: (transcript: string, isFinal: boolean) => void;
  onVoiceStart: () => void;
  onVoiceEnd: () => void;
  onError: (error: string) => void;
  disabled?: boolean;
  // New props for external control
  isListening?: boolean;
  onToggleListening?: () => void;
  // New props for backend integration
  onBackendResponse?: (response: any) => void;
  useBackendTranscription?: boolean; // Toggle between browser-only and backend processing
  userId?: string;
  apiEndpoint?: string;
}

interface BackendResponse {
  success: boolean;
  result: {
    response: string;
    transcribed_text?: string;
    audio_response?: string;
  };
  timestamp: string;
}

const VoiceInterface: React.FC<VoiceInterfaceProps> = ({
  onTranscript,
  onVoiceStart,
  onVoiceEnd,
  onError,
  disabled = false,
  isListening: externalIsListening,
  onToggleListening,
  onBackendResponse,
  useBackendTranscription = false,
  userId = "default_user",
  apiEndpoint = "/api/process",
}) => {
  const [internalIsListening, setInternalIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  // Recognition for UI feedback
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  // Audio recording for backend
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Add accumulated transcript to handle pauses
  const accumulatedTranscriptRef = useRef<string>("");
  const lastFinalTranscriptRef = useRef<string>("");

  // Use external control if provided, otherwise fall back to internal state
  const isListening =
    externalIsListening !== undefined
      ? externalIsListening
      : internalIsListening;
  const controlled = externalIsListening !== undefined;

  useEffect(() => {
    // Check if speech recognition is supported
    if (typeof window !== "undefined") {
      const SpeechRecognitionClass =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      if (SpeechRecognitionClass) {
        setIsSupported(true);
        initializeSpeechRecognition(SpeechRecognitionClass);
      } else {
        setIsSupported(false);
        console.warn(
          "SpeechRecognition not supported - backend transcription only mode"
        );
        // Still allow backend transcription even if browser recognition isn't supported
        if (useBackendTranscription) {
          setIsSupported(true);
        }
      }
    }
  }, [
    onTranscript,
    onVoiceStart,
    onVoiceEnd,
    onError,
    controlled,
    internalIsListening,
    externalIsListening,
    disabled,
    useBackendTranscription,
  ]);

  const initializeSpeechRecognition = (
    SpeechRecognitionClass: typeof SpeechRecognition
  ) => {
    const recognition = new SpeechRecognitionClass();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onstart = () => {
      console.log("Speech recognition started");
      // Reset accumulated transcript when starting
      accumulatedTranscriptRef.current = "";
      lastFinalTranscriptRef.current = "";

      if (!controlled) {
        setInternalIsListening(true);
      }
      onVoiceStart();
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      // Only process browser transcription if not using backend-only mode
      if (useBackendTranscription) {
        // In backend mode, we still show live feedback but don't rely on it for final processing
        let interimTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (!event.results[i].isFinal) {
            interimTranscript += transcript;
          }
        }
        // Only send interim results for UI feedback
        if (interimTranscript.trim()) {
          onTranscript(`[Preview] ${interimTranscript.trim()}`, false);
        }
        return;
      }

      // Original browser-only transcription logic
      let interimTranscript = "";
      let finalTranscript = "";

      // Process all results from the last processed index
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interimTranscript += transcript;
        }
      }

      // Handle final results - accumulate them
      if (finalTranscript) {
        // Only add new final transcript (avoid duplicates)
        if (finalTranscript !== lastFinalTranscriptRef.current) {
          accumulatedTranscriptRef.current +=
            (accumulatedTranscriptRef.current ? " " : "") +
            finalTranscript.trim();
          lastFinalTranscriptRef.current = finalTranscript;
        }
      }

      // Combine accumulated final transcript with current interim
      const fullTranscript =
        accumulatedTranscriptRef.current +
        (accumulatedTranscriptRef.current && interimTranscript ? " " : "") +
        interimTranscript;

      // Send the complete transcript (accumulated + interim)
      if (fullTranscript.trim()) {
        onTranscript(fullTranscript.trim(), !interimTranscript);
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error("Speech recognition error:", event.error);
      handleSpeechRecognitionError(event);
    };

    recognition.onend = () => {
      console.log("Speech recognition ended");
      handleSpeechRecognitionEnd();
    };

    recognitionRef.current = recognition;
  };

  const handleSpeechRecognitionError = (event: SpeechRecognitionErrorEvent) => {
    // Handle "aborted" specifically - don't show as error to user
    if (event.error === "aborted") {
      console.log("Speech recognition was aborted - this is normal behavior");
      if (!controlled) {
        setInternalIsListening(false);
      }
      onVoiceEnd();
      return;
    }

    // Handle "no-speech" - also normal, but restart recognition if still listening
    if (event.error === "no-speech") {
      console.log("No speech detected");
      // If we're still supposed to be listening, restart recognition
      if (isListening && !disabled) {
        console.log("Restarting recognition due to no-speech...");
        setTimeout(() => {
          if (
            recognitionRef.current &&
            (controlled ? externalIsListening : internalIsListening)
          ) {
            try {
              recognitionRef.current.start();
            } catch (restartError) {
              console.error("Failed to restart after no-speech:", restartError);
            }
          }
        }, 100);
      } else {
        if (!controlled) {
          setInternalIsListening(false);
        }
        onVoiceEnd();
      }
      return;
    }

    // Only show actual errors to user
    if (!["aborted", "no-speech"].includes(event.error)) {
      if (!controlled) {
        setInternalIsListening(false);
      }
      onError(`Speech recognition error: ${event.error}`);
      onVoiceEnd();
    }
  };

  const handleSpeechRecognitionEnd = () => {
    // If using backend transcription, process the recorded audio
    if (useBackendTranscription) {
      processRecordedAudio();
      return;
    }

    // Original browser-only logic
    const shouldStillListen = controlled
      ? externalIsListening
      : internalIsListening;

    if (shouldStillListen && !disabled) {
      console.log(
        "Recognition ended but should still be listening, restarting..."
      );
      setTimeout(() => {
        if (recognitionRef.current && shouldStillListen) {
          try {
            recognitionRef.current.start();
          } catch (restartError) {
            console.error("Failed to restart recognition:", restartError);
            if (!controlled) {
              setInternalIsListening(false);
            }
            onVoiceEnd();
          }
        }
      }, 100);
    } else {
      if (!controlled) {
        setInternalIsListening(false);
      }
      onVoiceEnd();
    }
  };

  // Effect to handle external listening state changes
  useEffect(() => {
    if (controlled && recognitionRef.current) {
      if (externalIsListening && !internalIsListening) {
        startListening();
      } else if (!externalIsListening && internalIsListening) {
        stopListening();
      }
    }
  }, [externalIsListening, controlled, internalIsListening]);

  const startAudioRecording = async (): Promise<boolean> => {
    if (!useBackendTranscription) return true;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "audio/mp4",
      });

      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        console.log("Audio recording stopped");
      };

      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;

      console.log("Audio recording started for backend processing");
      return true;
    } catch (error) {
      console.error("Error starting audio recording:", error);
      onError("Could not access microphone for recording");
      return false;
    }
  };

  const stopAudioRecording = () => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  };

  const processRecordedAudio = async () => {
    if (!useBackendTranscription || audioChunksRef.current.length === 0) {
      return;
    }

    setIsProcessing(true);

    try {
      // Create audio blob
      const audioBlob = new Blob(audioChunksRef.current, {
        type: mediaRecorderRef.current?.mimeType || "audio/webm",
      });

      // Convert to base64
      const base64Audio = await blobToBase64(audioBlob);

      // Send to backend
      const response = await fetch(apiEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          audio_data: base64Audio,
          user_id: userId,
          timestamp: new Date().toISOString(),
          input_method: "voice",
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result: BackendResponse = await response.json();

      if (result.success) {
        // Send the backend transcription as final result
        const backendTranscription =
          result.result.transcribed_text || result.result.response;

        if (backendTranscription) {
          // Clear any preview text and send the final transcription
          onTranscript(backendTranscription, true);
        }

        // Call the backend response handler if provided
        if (onBackendResponse) {
          onBackendResponse(result);
        }

        console.log("Backend processing successful:", result);
      } else {
        throw new Error("Backend processing failed");
      }
    } catch (error) {
      console.error("Error processing audio with backend:", error);
      onError("Failed to process audio. Please try again.");
    } finally {
      setIsProcessing(false);
      // Clean up
      audioChunksRef.current = [];
    }
  };

  const blobToBase64 = (blob: Blob): Promise<string> => {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64String = (reader.result as string).split(",")[1];
        resolve(base64String);
      };
      reader.readAsDataURL(blob);
    });
  };

  const startListening = async () => {
    if (!isSupported || disabled) return;

    // Reset transcript accumulation
    accumulatedTranscriptRef.current = "";
    lastFinalTranscriptRef.current = "";

    try {
      // Start audio recording if using backend transcription
      if (useBackendTranscription) {
        const audioStarted = await startAudioRecording();
        if (!audioStarted) return;
      }

      // Start speech recognition for UI feedback (if supported)
      if (recognitionRef.current) {
        setInternalIsListening(true);
        recognitionRef.current.start();
      } else if (useBackendTranscription) {
        // Backend-only mode without browser recognition
        if (!controlled) {
          setInternalIsListening(true);
        }
        onVoiceStart();
      }
    } catch (error: any) {
      console.error("Error starting speech recognition:", error);

      // Clean up audio recording if it was started
      stopAudioRecording();

      // If recognition is already started, try to stop and restart
      if (error.name === "InvalidStateError" && recognitionRef.current) {
        console.log("Recognition already started, attempting restart...");
        try {
          recognitionRef.current.stop();
          setTimeout(async () => {
            if (recognitionRef.current) {
              if (useBackendTranscription) {
                await startAudioRecording();
              }
              recognitionRef.current.start();
            }
          }, 200);
        } catch (restartError) {
          console.error("Failed to restart recognition:", restartError);
          setInternalIsListening(false);
          onError("Failed to start speech recognition");
        }
      } else {
        setInternalIsListening(false);
        onError("Failed to start speech recognition");
      }
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      setInternalIsListening(false);
      recognitionRef.current.stop();
    }

    // Stop audio recording
    stopAudioRecording();

    // If we're in backend-only mode and don't have speech recognition
    if (useBackendTranscription && !recognitionRef.current) {
      if (!controlled) {
        setInternalIsListening(false);
      }
      onVoiceEnd();
      // Process the recorded audio
      processRecordedAudio();
    }
  };

  const handleToggle = () => {
    if (isProcessing) return; // Don't allow toggling while processing

    if (controlled && onToggleListening) {
      onToggleListening();
    } else {
      // Uncontrolled mode
      if (isListening) {
        stopListening();
      } else {
        startListening();
      }
    }
  };

  if (!isSupported) {
    return (
      <div className="flex items-center justify-center">
        <div className="bg-red-100 text-red-700 px-4 py-2 rounded-lg text-sm">
          Voice input not supported in this browser
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={handleToggle}
      disabled={disabled || isProcessing}
      className={`
        rounded-full p-3 text-2xl flex items-center justify-center disabled:opacity-50 mx-2 relative
        ${
          isListening
            ? "bg-red-100 hover:bg-red-200 animate-pulse"
            : "bg-gray-100 hover:bg-gray-200"
        }
        ${isProcessing ? "cursor-not-allowed" : "cursor-pointer"}
      `}
      title={
        isProcessing
          ? "Processing audio..."
          : isListening
          ? "Click to stop recording"
          : "Click to start recording"
      }
    >
      {isProcessing ? (
        <div className="flex items-center justify-center">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      ) : isListening ? (
        <div className="flex items-center justify-center">
          <div className="w-3 h-3 bg-red-500 rounded-full animate-ping"></div>
        </div>
      ) : (
        "🎤"
      )}

      {/* Small indicator for backend mode */}
      {useBackendTranscription && (
        <div
          className="absolute -top-1 -right-1 w-3 h-3 bg-blue-500 rounded-full border-2 border-white"
          title="Using backend transcription"
        ></div>
      )}
    </button>
  );
};

export default VoiceInterface;
