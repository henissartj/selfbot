import subprocess
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

def start_bot(token):
    if is_bot_running():
        return False, "Already running"

    # Use system python3 (which has discord.py-self installed)
    # We try to use /usr/bin/python3 to avoid using the venv's python
    python_executable = "/usr/bin/python3"
    if not os.path.exists(python_executable):
        # Fallback if not on Linux standard path
        python_executable = "python3"

    env = os.environ.copy()
    env["DISCORD_TOKEN"] = token
    
    try:
        # Open log file
        log_file = open("selfbot.log", "a")
        
        # Start subprocess detached
        # selfbot.py MUST be in the same directory
        p = subprocess.Popen(
            [python_executable, "selfbot.py"],
            env=env,
            cwd=os.getcwd(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
        # Write PID
        with open(PID_FILE, 'w') as f:
            f.write(str(p.pid))
            
        # Wait a bit to see if it crashes immediately
        time.sleep(3)
        if p.poll() is not None:
             return False, f"Failed to start (Exit code: {p.returncode})"
             
        return True, "Started"
    except Exception as e:
        return False, f"Error launching: {e}"

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
