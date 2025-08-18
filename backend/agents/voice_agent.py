import os
import sys
from google.cloud import speech
import asyncio
from typing import Any, Dict
import logging
logger = logging.getLogger(__name__)

# Handle imports - try relative first, then absolute
try:
    from .base_agent import BaseAgent
    from ..core.sessionManager import SessionManager
except ImportError:
    # Add parent directories to path for absolute imports
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(current_dir)
    project_dir = os.path.dirname(backend_dir)
    
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    
    try:
        from agents.base_agent import BaseAgent
        from core.sessionManager import SessionManager
    except ImportError:
        # Fallback: try importing from current directory
        from base_agent import BaseAgent
        from sessionManager import SessionManager

class VoiceAgent(BaseAgent):
    def __init__(self, session_manager: SessionManager):
        super().__init__(name="VoiceAgent")
        self.session_manager = session_manager
        self.stt_client = speech.SpeechClient()
        #self.tts_client = texttospeech.TextToSpeechClient()

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process input data for speech-to-text or text-to-speech.
        
        Args:
            input_data: Dictionary containing 'action' and 'audio_file_path' or 'text'.
            
        Returns:
            Dictionary with processed results.
        """

        try:
            voice_output = {}
            mode = input_data.get("action")
            
            if mode == "transcribe":
                audio_file_path = input_data.get("audio_file_path") or input_data.get("audio_data")
                if not audio_file_path:
                    return self._create_response({"error": "Missing audio file path"}, status="error")
                transcript = self.speech_to_text(audio_file_path)  # Fixed: pass the path directly
                voice_output["transcript"] = transcript
                logger.info(f"Transcribing voice done {transcript[:50]}...")
                return self._create_response(voice_output)
            
            elif mode == "text-to-speech":
                text = input_data.get("text")
                if not text:
                    return self._create_response({"error": "Missing text"}, status="error")
                output_file_path = self.text_to_speech(text)
                return self._create_response({"output_file": output_file_path})
            
            else:
                return self._create_response({"error": "Invalid mode"}, status="error")

        except Exception as e:
            self.logger.error(f"Error processing input: {e}")
            return self._handle_error(e)

    def speech_to_text(self, audio_file_path: str) -> str:
        """
        Convert speech audio file to text using Google Cloud Speech-to-Text.
        
        Args:
            audio_file_path: Path to the audio file to transcribe.
            
        Returns:
            Transcribed text from the audio.
        """

        with open(audio_file_path, "rb") as audio_file:
            content = audio_file.read()

        audio = speech.RecognitionAudio(content=content)
        
        # Auto-detect configuration - let Google Cloud determine the format
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            # Omit sample_rate_hertz to let Google auto-detect from WAV header
            language_code="en-US",
            # Enable automatic punctuation for better output
            enable_automatic_punctuation=True,
            # Use enhanced model for better accuracy
            use_enhanced=True,
            model='latest_long'
        )

        try:
            response = self.stt_client.recognize(config=config, audio=audio)
            
            # Combine results into a single transcript
            transcript = " ".join(result.alternatives[0].transcript for result in response.results)
            return transcript if transcript else "No speech detected in audio file"
            
        except Exception as e:
            # If auto-detection fails, try with common sample rates
            common_rates = [44100, 48000, 16000, 8000]
            for rate in common_rates:
                try:
                    config.sample_rate_hertz = rate
                    response = self.stt_client.recognize(config=config, audio=audio)
                    transcript = " ".join(result.alternatives[0].transcript for result in response.results)
                    return transcript if transcript else "No speech detected in audio file"
                except:
                    continue
            
            # If all rates fail, raise the original exception
            raise e
    
# async def main():
#     # Initialize session manager
#     # session_manager = SessionManager(session_timeout_minutes=30)

#     agent = VoiceAgent()

#     # Example 1: Convert speech audio file to text
#     original_audio = "Test-audio.wav"

#     # Create input data with correct structure
#     input_data = {
#         "audio_data": original_audio,  # This will be used as audio_file_path
#         "action": "transcribe"
#     }
    
#     try:
#         # Fixed: Added await since process is an async method
#         result = await agent.process(input_data)
#         if result.get("status") == "success":
#             transcript = result["data"]["transcript"]
#             print(f"Transcript from '{original_audio}':\n{transcript}")
#         else:
#             error_msg = result.get("data", {}).get("error", "Unknown error")
#             print(f"Error: {error_msg}")
            
#     except Exception as e:
#         print(f"Error in speech-to-text: {e}")

# if __name__ == "__main__":
#     # Run the async main function
#     asyncio.run(main())