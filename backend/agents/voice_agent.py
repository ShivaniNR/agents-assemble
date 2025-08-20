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
                
                logger.info(f"Processing audio file: {audio_file_path}")
                
                # Check if file exists
                if not os.path.exists(audio_file_path):
                    logger.error(f"Audio file not found: {audio_file_path}")
                    return self._create_response({"error": f"Audio file not found: {audio_file_path}"}, status="error")
                
                # Get file size for logging
                file_size = os.path.getsize(audio_file_path)
                logger.info(f"Audio file size: {file_size} bytes")
                
                transcript = self.speech_to_text(audio_file_path)
                voice_output["transcript"] = transcript
                logger.info(f"Transcribing voice done: '{transcript[:50]}...'")
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
        logger.info(f"Starting speech to text conversion for file: {audio_file_path}")
        
        # Check file extension to determine format
        file_ext = os.path.splitext(audio_file_path)[1].lower()
        logger.info(f"File extension: {file_ext}")
        
        with open(audio_file_path, "rb") as audio_file:
            content = audio_file.read()
            logger.info(f"Read {len(content)} bytes from audio file")

        audio = speech.RecognitionAudio(content=content)
        
        # Configure based on file type
        if file_ext == '.webm':
            # WebM files typically use OGG_OPUS encoding
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
                sample_rate_hertz=48000,  # Common for WebM
                language_code="en-US",
                enable_automatic_punctuation=True,
                use_enhanced=True,
                model='latest_long',
                audio_channel_count=1  # Mono audio is common for recordings
            )
            logger.info("Using OGG_OPUS encoding for WebM file")
        else:
            # Default configuration for other formats
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                language_code="en-US",
                enable_automatic_punctuation=True,
                use_enhanced=True,
                model='latest_long'
            )
            logger.info(f"Using LINEAR16 encoding for {file_ext} file")

        try:
            logger.info("Sending request to Google Speech-to-Text API...")
            response = self.stt_client.recognize(config=config, audio=audio)
            
            logger.info(f"Received response with {len(response.results)} results")
            
            # Combine results into a single transcript
            if response.results:
                transcript = " ".join(result.alternatives[0].transcript for result in response.results)
                logger.info(f"Transcription successful: '{transcript[:50]}...'")
                return transcript
            else:
                logger.warning("No results returned from Speech-to-Text API")
                
                # Try alternative encodings if no results
                logger.info("Trying alternative encoding: WEBM_OPUS")
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                    sample_rate_hertz=48000,
                    language_code="en-US",
                    enable_automatic_punctuation=True,
                    use_enhanced=True,
                    model='latest_long'
                )
                
                response = self.stt_client.recognize(config=config, audio=audio)
                if response.results:
                    transcript = " ".join(result.alternatives[0].transcript for result in response.results)
                    logger.info(f"WEBM_OPUS encoding successful: '{transcript[:50]}...'")
                    return transcript
                else:
                    logger.warning("No results with WEBM_OPUS encoding either")
                    return "No speech detected in audio file"
            
        except Exception as e:
            logger.error(f"Error in speech_to_text: {str(e)}")
            
            # Try with common sample rates and different encodings
            encodings = [
                (speech.RecognitionConfig.AudioEncoding.LINEAR16, "LINEAR16"),
                (speech.RecognitionConfig.AudioEncoding.OGG_OPUS, "OGG_OPUS"),
                (speech.RecognitionConfig.AudioEncoding.WEBM_OPUS, "WEBM_OPUS"),
                (speech.RecognitionConfig.AudioEncoding.MP3, "MP3")
            ]
            
            common_rates = [48000, 44100, 16000, 8000]
            
            logger.info("Trying fallback configurations...")
            
            for encoding, encoding_name in encodings:
                for rate in common_rates:
                    try:
                        logger.info(f"Trying with encoding {encoding_name}, rate {rate}")
                        config = speech.RecognitionConfig(
                            encoding=encoding,
                            sample_rate_hertz=rate,
                            language_code="en-US",
                            enable_automatic_punctuation=True,
                            use_enhanced=True,
                            model='latest_long'
                        )
                        response = self.stt_client.recognize(config=config, audio=audio)
                        
                        if response.results:
                            transcript = " ".join(result.alternatives[0].transcript for result in response.results)
                            logger.info(f"Fallback successful with {encoding_name}, {rate}: '{transcript[:50]}...'")
                            return transcript
                    except Exception as inner_e:
                        logger.debug(f"Fallback failed with {encoding_name}, {rate}: {str(inner_e)}")
                        continue
            
            # If all attempts fail, log the detailed error and return a generic message
            logger.error(f"All transcription attempts failed. Original error: {str(e)}")
            return "Could not transcribe audio. Speech recognition failed."
    
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
