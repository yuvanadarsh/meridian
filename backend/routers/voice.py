"""Voice routes: text-to-speech via ElevenLabs.

Implemented in the push-to-talk voice build step.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/voice", tags=["voice"])
