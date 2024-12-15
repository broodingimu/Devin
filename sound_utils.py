import platform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def play_beep(frequency=1000, duration=500):
    """Cross-platform implementation of system beep.

    Args:
        frequency (int): Frequency in Hz (Windows only)
        duration (int): Duration in milliseconds
    """
    system = platform.system().lower()

    try:
        if system == 'windows':
            import winsound
            winsound.Beep(frequency, duration)
        elif system in ('linux', 'darwin'):
            # Use console bell on Linux/macOS
            print('\a', flush=True)
        else:
            logger.warning(f"Beep not implemented for system: {system}")
    except Exception as e:
        logger.error(f"Failed to play beep sound: {str(e)}")
