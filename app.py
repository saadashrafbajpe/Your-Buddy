import json
import os
import threading
import time
from datetime import datetime
import re
import webbrowser
import math
import ast
import operator as op

import speech_recognition as sr
import pyttsx3
import pywhatkit
import datetime as dt
import wikipedia
import pyjokes

# ---------------- Persistent notes ----------------
NOTES_FILE = "assistant_notes.json"

def load_notes():
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_notes(notes):
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
            return True
    except Exception as e:
        print("Failed to save notes:", e)
        return False

# ---------------- TTS (keeps your existing talk/speak_long) ----------------
ENGINE_LOCK = threading.Lock()
_engine = None

def _init_engine():
    """(Re)initialize engine and set properties."""
    global _engine
    try:
        _engine = pyttsx3.init()
        voices = _engine.getProperty('voices')
        if len(voices) > 0:
            _engine.setProperty('voice', voices[0].id)
        _engine.setProperty('rate', 150)
        _engine.setProperty('volume', 1.0)
    except Exception as e:
        print("Failed to (re)initialize TTS engine:", e)
        _engine = None

_init_engine()

def _safe_run_say(text):
    global _engine
    if _engine is None:
        return False
    with ENGINE_LOCK:
        try:
            _engine.say(text)
            _engine.runAndWait()
            return True
        except Exception as e:
            print("TTS error while running:", e)
            return False

def talk(text):
    if not text:
        return
    print("TTS ->", text)
    ok = _safe_run_say(text)
    if ok:
        return
    # fallback: try re-init once
    print("Reinitializing TTS engine and retrying...")
    _init_engine()
    ok = _safe_run_say(text)
    if not ok:
        print("TTS final failure. Outputting text instead:")
        print(text)

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
def speak_long(text, max_chunk_chars=250):
    if not text:
        return
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    chunk = ""
    for p in parts:
        if not p:
            continue
        if len(chunk) + len(p) + 1 <= max_chunk_chars:
            chunk = (chunk + " " + p).strip()
        else:
            talk(chunk)
            chunk = p
    if chunk:
        talk(chunk)

# ---------------- Safe math evaluator ----------------
# Allowed operators for safe evaluation
_ALLOWED_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}

def safe_eval(expr: str):
    """
    Safely evaluate simple arithmetic expressions using ast.
    Supports numbers and + - * / ** % // and unary + -.
    """
    try:
        node = ast.parse(expr, mode='eval').body
    except Exception as e:
        raise ValueError("Invalid expression") from e

    def _eval(n):
        if isinstance(n, ast.Num):  # <number>
            return n.n
        if isinstance(n, ast.UnaryOp) and type(n.op) in _ALLOWED_OPERATORS:
            return _ALLOWED_OPERATORS[type(n.op)](_eval(n.operand))
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_OPERATORS:
            return _ALLOWED_OPERATORS[type(n.op)](_eval(n.left), _eval(n.right))
        raise ValueError("Unsupported expression element: {}".format(type(n).__name__))

    return _eval(node)

# ---------------- Speech recognition ----------------
listener = sr.Recognizer()

def take_command(timeout=5, phrase_time_limit=7):
    command = ""
    try:
        with sr.Microphone() as source:
            print("listening...")
            listener.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = listener.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                print("recognizing...")
                command = listener.recognize_google(audio).lower()
                print("You said:", command)
            except sr.WaitTimeoutError:
                print("No speech detected (timeout).")
            except sr.UnknownValueError:
                print("Could not understand audio.")
            except sr.RequestError as e:
                print("Could not request results from Google SR service; ", e)
            except Exception as e:
                print("Unexpected error while listening:", e)
    except Exception as e:
        print("Microphone error (maybe no microphone or busy):", e)

    if 'alexa' in command:
        command = command.replace('alexa', '').strip()
        print("Command after removing trigger word:", command)

    return command

# ---------------- Timer helper ----------------
def _timer_thread(seconds, label=None):
    label_text = (" (" + label + ")") if label else ""
    print(f"Timer started for {seconds} seconds{label_text}")
    # attempt to speak when timer finishes
    time.sleep(seconds)
    message = f"Timer finished{label_text}."
    print(message)
    try:
        talk(message)
    except Exception as e:
        print("Timer TTS failed:", e)

def set_timer(seconds, label=None):
    th = threading.Thread(target=_timer_thread, args=(seconds,label), daemon=True)
    th.start()

# ---------------- Assistant features ----------------
def print_help():
    help_text = """
Supported commands (examples):
- play <song name>                -> plays song on YouTube
- play music [<query>]            -> opens music search on YouTube
- time                            -> tells current time
- who is <person>                 -> short Wikipedia info
- wikipedia <query>               -> longer Wikipedia summary
- joke                            -> tells a joke
- note <text>  OR remember <text> -> save a note
- show notes                      -> display saved notes
- delete notes                    -> delete all saved notes
- set a timer for 5 minutes       -> set a timer (seconds/minutes)
- calculate <expression>          -> compute basic arithmetic (safe)
- test voice                      -> verify TTS attempt
- open youtube / open google      -> open sites
- help                            -> show this help
"""
    print(help_text)
    talk("Here are the commands I support. Check the console for details.")

# ---------------- Main assistant logic ----------------
# greet once
talk('Hi There. I am Your Buddy, your personal AI assistant. How may I help you?')
print_help()

def run_alexa():
    command = take_command()
    if not command:
        talk("I didn't hear you. Please say the command again.")
        return

    print("Processing command:", command)

    # play <song>
    if 'play' in command and 'play music' not in command:
        song = command.replace('play', '').strip()
        if song:
            talk('playing ' + song)
            try:
                pywhatkit.playonyt(song)
            except Exception as e:
                print("Error playing song via pywhatkit:", e)
                talk("Sorry, I couldn't play that song.")
        else:
            talk("Which song should I play?")

    # play music search
    elif 'play music' in command:
        search_term = command.replace("play music", "").strip()
        if not search_term:
            search_term = "top songs"
        url = "https://www.youtube.com/results?search_query=" + search_term.replace(" ", "+")
        try:
            webbrowser.open(url)
            talk("Opened music search on YouTube.")
        except Exception as e:
            print("Failed to open web browser:", e)
            talk("Sorry, I couldn't open YouTube.")

    # time
    elif 'time' in command:
        now = dt.datetime.now().strftime('%I:%M %p')
        talk('Current time is ' + now)

    # who is
    elif 'who is' in command:
        person = command.replace('who is', '').strip()
        if person:
            try:
                info = wikipedia.summary(person, sentences=1)
                print(info)
                speak_long(info)
            except Exception as e:
                print("Wikipedia error:", e)
                talk("Sorry, I couldn't find that on Wikipedia.")
        else:
            talk("Who do you want to search on Wikipedia?")

    # wikipedia query
    elif 'wikipedia' in command:
        talk('Searching Wikipedia')
        query = command.replace("wikipedia", "").strip()
        if query:
            try:
                results = wikipedia.summary(query, sentences=2)
                talk('According to Wikipedia')
                print(results)
                speak_long(results)
            except Exception as e:
                print("Wikipedia lookup failed:", e)
                talk("Sorry, I could not retrieve results from Wikipedia.")
        else:
            talk("What do you want me to search on Wikipedia?")

    # jokes
    elif 'joke' in command:
        try:
            joke = pyjokes.get_joke()
            print("Joke:", joke)
            speak_long(joke)
        except Exception as e:
            print("Failed to get joke:", e)
            talk("Sorry, I couldn't fetch a joke right now.")

    # NOTES: take / remember
    elif command.startswith("note ") or command.startswith("remember "):
        # capture everything after first word
        text = re.split(r'\s+', command, maxsplit=1)[1].strip()
        notes = load_notes()
        notes.append({"text": text, "created": datetime.now().isoformat()})
        if save_notes(notes):
            talk("Note saved.")
            print("Saved note:", text)
        else:
            talk("Failed to save the note. See console for errors.")

    elif 'show notes' in command:
        notes = load_notes()
        if not notes:
            talk("You have no saved notes.")
            print("No saved notes.")
        else:
            talk(f"You have {len(notes)} notes. Printing them now.")
            for i, n in enumerate(notes, 1):
                s = f"{i}. {n.get('text')} (saved {n.get('created','')})"
                print(s)
                speak_long(s, max_chunk_chars=150)

    elif 'delete notes' in command:
        # simple confirmation via TTS/text (no extra listening)
        talk("Deleting all notes now.")
        save_notes([])
        print("All notes deleted.")

    # set a timer
    elif re.search(r'set (a )?timer for (\d+)\s*(seconds|second|minutes|minute|mins|min|hrs|hours|hour)?', command):
        m = re.search(r'(\d+)\s*(seconds|second|minutes|minute|mins|min|hrs|hours|hour)?', command)
        if m:
            value = int(m.group(1))
            unit = m.group(2) or "seconds"
            if unit.startswith('min') or unit.startswith('hour') or unit.startswith('hr'):
                if unit.startswith('hour') or unit.startswith('hr'):
                    sec = value * 3600
                else:
                    sec = value * 60
            else:
                sec = value
            set_timer(sec)
            talk(f"Timer set for {value} {unit}.")
        else:
            talk("I couldn't parse the timer length. Say for example: set a timer for 5 minutes.")

    # calculate
    elif 'calculate' in command:
        expr = command.replace('calculate', '').strip()
        if not expr:
            talk("What do you want me to calculate?")
        else:
            try:
                result = safe_eval(expr)
                talk(f"The result is {result}")
                print(f"{expr} = {result}")
            except Exception as e:
                print("Calculation error:", e)
                talk("Sorry, I couldn't evaluate that expression. Use numbers and + - * / ** % // only.")

    # test tts
    elif 'test voice' in command or 'test tts' in command:
        print("Running TTS test...")
        try:
            talk("Testing text to speech. One two three.")
            print("TTS test attempted. If you heard spoken words, voice works here.")
        except Exception as e:
            print("TTS test failed:", e)
            print("Only text output will display if TTS is unavailable.")

    elif 'open youtube' in command:
        try:
            webbrowser.open("https://youtube.com")
            talk("Opening YouTube.")
        except Exception as e:
            print("Failed to open YouTube:", e)
            talk("Sorry, I couldn't open YouTube.")

    elif 'open google' in command:
        try:
            webbrowser.open("https://google.com")
            talk("Opening Google.")
        except Exception as e:
            print("Failed to open Google:", e)
            talk("Sorry, I couldn't open Google.")

    elif 'help' in command:
        print_help()

    else:
        talk('Please say the command again.')

# ---------------- Main loop ----------------
if __name__ == "__main__":
    try:
        while True:
            run_alexa()
            time.sleep(0.3)
    except KeyboardInterrupt:
        talk("Shutting down. Goodbye!")
    except Exception as e:
        print("Unexpected error in main loop:", e)
        talk("An unexpected error occurred. Shutting down.")
