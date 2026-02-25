import multiprocessing
import os
import signal
import sys
import time
import selfbot

# PID file to track the process
PID_FILE = "bot.pid"

def is_bot_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process exists
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
        except (ValueError, Exception):
            return False
    return False

def _run_bot_process(token):
    # Wrapper to run the bot
    # Write PID to file
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
        
    try:
        # Redirect stdout/stderr to log file if needed, or just let it print
        # For now, we keep it simple
        selfbot.run_bot(token)
    except Exception as e:
        print(f"Bot process crashed: {e}", file=sys.stderr)
    finally:
        # Cleanup PID file on exit
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except:
                pass

def start_bot(token):
    if is_bot_running():
        return False, "Already running"

    # Start bot in a separate process
    p = multiprocessing.Process(target=_run_bot_process, args=(token,))
    p.daemon = True
    p.start()
    
    # Wait a bit to see if it crashes immediately
    time.sleep(2)
    if not is_bot_running():
        return False, "Failed to start (crashed immediately)"
        
    return True, "Started"

def stop_bot():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            
            # Force cleanup if still exists
            if os.path.exists(PID_FILE):
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
                try:
                    os.remove(PID_FILE)
                except:
                    pass
            return True, "Stopped"
        except Exception as e:
            # Try to clean up file anyway
            if os.path.exists(PID_FILE):
                try:
                    os.remove(PID_FILE)
                except:
                    pass
            return False, f"Error stopping: {e}"
    return False, "Not running"
