import subprocess
import os
import signal
import sys
import time
import json

# Directory to store PIDs
PID_DIR = "pids"
LOG_DIR = "logs"

def _ensure_dirs():
    if not os.path.exists(PID_DIR):
        os.makedirs(PID_DIR)
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

def get_pid_file(user_id):
    _ensure_dirs()
    return os.path.join(PID_DIR, f"{user_id}.pid")

def get_log_file(user_id):
    _ensure_dirs()
    return os.path.join(LOG_DIR, f"{user_id}.log")

def is_bot_running(user_id):
    pid_file = get_pid_file(user_id)
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process exists
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                # Process dead, cleanup
                try:
                    os.remove(pid_file)
                except:
                    pass
                return False
        except (ValueError, Exception):
            return False
    return False

def start_bot(user_id, token):
    if is_bot_running(user_id):
        return False, "Already running"

    python_executable = "/usr/bin/python3"
    if not os.path.exists(python_executable):
        python_executable = "python3"

    env = os.environ.copy()
    env["DISCORD_TOKEN"] = token
    
    try:
        log_path = get_log_file(user_id)
        log_file = open(log_path, "a")
        
        p = subprocess.Popen(
            [python_executable, "selfbot.py"],
            env=env,
            cwd=os.getcwd(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
        with open(get_pid_file(user_id), 'w') as f:
            f.write(str(p.pid))
            
        time.sleep(3)
        if p.poll() is not None:
            error_msg = f"Exit code: {p.returncode}"
            try:
                with open(log_path, "r") as lf:
                    lines = lf.readlines()
                    last_lines = lines[-10:] if len(lines) > 10 else lines
                    error_details = "".join(last_lines)
                    error_msg += f"\nLogs:\n{error_details}"
            except:
                error_msg += " (Could not read logs)"
            return False, f"Failed: {error_msg}"
             
        return True, "Started"
    except Exception as e:
        return False, f"Error launching: {e}"

def stop_bot(user_id):
    pid_file = get_pid_file(user_id)
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            
            if os.path.exists(pid_file):
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
                try:
                    os.remove(pid_file)
                except:
                    pass
            return True, "Stopped"
        except Exception as e:
            if os.path.exists(pid_file):
                try:
                    os.remove(pid_file)
                except:
                    pass
            return False, f"Error stopping: {e}"
    return False, "Not running"
