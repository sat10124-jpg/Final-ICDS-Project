"""
gui.py - Tkinter GUI for the chat client
Handles all socket communication directly to avoid threading conflicts.

Enhanced with:
  - AI Picture Generation (/aipic: <prompt>)
  - NLP Chat Summary (/summary) and Keyword Extraction (/keywords)
  - Sentiment analysis on all messages
  - Collapsible + menu for utility commands
  - Polished slate/indigo dark color scheme
"""

import threading
import socket
import json
import queue
import time
import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox
from chat_utils import *
from chat_bot_client import ChatBotClient
from textblob import TextBlob

import re
import string
from collections import Counter

try:
    import nltk
    for _pkg in ("punkt", "stopwords", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{_pkg}" if _pkg.startswith("punkt") else f"corpora/{_pkg}")
        except LookupError:
            nltk.download(_pkg, quiet=True)
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize, sent_tokenize
    NLTK_OK = True
except Exception:
    NLTK_OK = False

try:
    from PIL import Image, ImageTk
    import urllib.request
    import urllib.parse
    import io
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ── Color palette (deep slate + indigo) ──────────────────────────────────────
C = {
    "bg_app":    "#1a1d2e",
    "bg_header": "#222640",
    "bg_chat":   "#141624",
    "bg_input":  "#222640",
    "bg_panel":  "#1a1d2e",
    "accent":    "#6c63ff",
    "green":     "#22c55e",
    "amber":     "#f59e0b",
    "purple":    "#a855f7",
    "border":    "#2d3158",
    "popup_bg":  "#252945",
    "txt_main":  "#e2e4f0",
    "txt_muted": "#7b82a8",
    "txt_me":    "#818cf8",
    "txt_peer":  "#f87171",
    "txt_sys":   "#94a3b8",
    "txt_bot":   "#c084fc",
    "txt_nlp":   "#4ade80",
    "txt_pic":   "#fb923c",
}

S_LOGGEDIN = 1
S_CHATTING = 2


def get_sentiment(text):
    p = TextBlob(text).sentiment.polarity
    return "😊 Positive" if p > 0.1 else ("😡 Negative" if p < -0.1 else "😐 Neutral")


def extract_keywords(messages, top_n=10):
    combined = " ".join(messages).lower().translate(str.maketrans("", "", string.punctuation))
    if NLTK_OK:
        tokens = word_tokenize(combined)
        stops = set(stopwords.words("english"))
    else:
        tokens = combined.split()
        stops = {"i","me","my","we","our","you","your","he","she","it","they","their",
                 "this","that","is","are","was","were","be","been","have","has","had",
                 "do","does","did","will","would","could","should","a","an","the",
                 "and","but","or","so","if","in","on","at","to","for","of","with",
                 "by","from","as","up","not","no","just","ok","okay","yeah"}
    words = [w for w in tokens if w.isalpha() and w not in stops and len(w) > 2]
    return Counter(words).most_common(top_n)


def generate_summary(messages, num_sentences=3):
    if not messages:
        return "No messages to summarize."
    combined = " ".join(messages)
    sents = sent_tokenize(combined) if NLTK_OK else re.split(r'(?<=[.!?])\s+', combined)
    if len(sents) <= num_sentences:
        return combined
    kws = {w for w, _ in extract_keywords(messages, top_n=20)}
    scores = {i: sum(1 for w in s.lower().split() if w in kws) for i, s in enumerate(sents)}
    top = sorted(sorted(scores, key=scores.get, reverse=True)[:num_sentences])
    return " ".join(sents[i] for i in top)


def fetch_ai_image(prompt, width=400, height=300):
    if not PIL_OK:
        return None, "Install Pillow: pip install Pillow"
    try:
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width={width}&height={height}&nologo=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        img = Image.open(io.BytesIO(data))
        img.thumbnail((400, 300), Image.LANCZOS)
        return ImageTk.PhotoImage(img), None
    except Exception as e:
        return None, str(e)


def mk_btn(parent, text, cmd, bg, fg="#ffffff", font_size=10, padx=12):
    """Uniform flat button factory."""
    return tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
        font=("Segoe UI", font_size, "bold"),
        relief=tk.FLAT, bd=0, cursor="hand2",
        padx=padx, pady=0, height=1,
    )


class ChatGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("💬  Chat")
        self.root.geometry("600x700")
        self.root.configure(bg=C["bg_app"])
        self.root.resizable(True, True)

        self.s = None
        self.me = ""
        self.peer = ""
        self.state = S_LOGGEDIN
        self.running = False
        self.msg_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.sock_lock = threading.Lock()
        self.bot = ChatBotClient(name="Bot", model="phi4-mini")
        self.chat_history = []
        self._image_refs = []
        self._menu_visible = False

        self._build_ui()
        self._login()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Status bar
        self.status_var = tk.StringVar(value="Not connected")
        tk.Label(self.root, textvariable=self.status_var,
                 bg=C["bg_header"], fg=C["txt_muted"],
                 font=("Segoe UI", 9), anchor="w", padx=14, pady=7
                 ).pack(fill=tk.X)

        # Chat display
        self.chat_display = scrolledtext.ScrolledText(
            self.root, state="disabled", wrap=tk.WORD,
            bg=C["bg_chat"], fg=C["txt_main"],
            font=("Segoe UI", 11), insertbackground=C["txt_main"],
            relief=tk.FLAT, bd=0, padx=14, pady=12,
            selectbackground=C["accent"], selectforeground="#ffffff",
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        self.chat_display.tag_config("me",     foreground=C["txt_me"],   font=("Segoe UI", 11, "bold"))
        self.chat_display.tag_config("peer",   foreground=C["txt_peer"], font=("Segoe UI", 11, "bold"))
        self.chat_display.tag_config("system", foreground=C["txt_sys"],  font=("Segoe UI", 10, "italic"))
        self.chat_display.tag_config("bot",    foreground=C["txt_bot"],  font=("Segoe UI", 11, "bold"))
        self.chat_display.tag_config("nlp",    foreground=C["txt_nlp"],  font=("Segoe UI", 10, "italic"))
        self.chat_display.tag_config("aipic",  foreground=C["txt_pic"],  font=("Segoe UI", 10, "bold"))

        # ── Collapsible utility menu ──────────────────────────────────────────
        self._menu_frame = tk.Frame(self.root, bg=C["popup_bg"], pady=6, padx=8)
        for label, cmd in [
            ("Who's Online", self._who),
            ("Connect",      self._connect_peer),
            ("Time",         self._time),
            ("Disconnect",   self._disconnect_peer),
            ("Clear Chat",   self._clear_chat),
        ]:
            mk_btn(self._menu_frame, label, cmd, bg=C["bg_header"], padx=10
                   ).pack(side=tk.LEFT, padx=3, pady=2, ipady=5)

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)

        # ── Bottom panel ──────────────────────────────────────────────────────
        panel = tk.Frame(self.root, bg=C["bg_panel"], pady=10, padx=10)
        panel.pack(fill=tk.X)

        # Row 1 — main message input
        r1 = tk.Frame(panel, bg=C["bg_panel"])
        r1.pack(fill=tk.X, pady=(0, 8))

        self._plus_btn = mk_btn(r1, "+", self._toggle_menu,
                                bg=C["bg_input"], fg=C["txt_muted"], padx=10)
        self._plus_btn.pack(side=tk.LEFT, ipady=7)
        tk.Frame(r1, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        self.msg_input = tk.Entry(
            r1, font=("Segoe UI", 12),
            bg=C["bg_input"], fg=C["txt_main"],
            insertbackground=C["txt_main"],
            relief=tk.FLAT, bd=0,
        )
        self.msg_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7, padx=(2, 8))
        self.msg_input.bind("<Return>", lambda e: self._send_message())

        mk_btn(r1, "Send ▶", self._send_message,
               bg=C["accent"], padx=18, font_size=10
               ).pack(side=tk.LEFT, ipady=7)

        # Row 2 — NLP | AI Pic | Bot (uniform height via ipady)
        r2 = tk.Frame(panel, bg=C["bg_panel"])
        r2.pack(fill=tk.X)

        # NLP
        tk.Label(r2, text="NLP", bg=C["bg_panel"], fg=C["txt_muted"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 3))
        mk_btn(r2, "Summary",  self._nlp_summary,  bg=C["green"],  padx=10).pack(side=tk.LEFT, ipady=7, padx=(0, 3))
        mk_btn(r2, "Keywords", self._nlp_keywords, bg=C["green"],  padx=10).pack(side=tk.LEFT, ipady=7, padx=(0, 12))

        # AI Pic
        tk.Label(r2, text="AI Pic", bg=C["bg_panel"], fg=C["txt_muted"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 3))
        self.aipic_input = tk.Entry(
            r2, font=("Segoe UI", 11),
            bg=C["bg_input"], fg=C["txt_main"],
            insertbackground=C["txt_main"],
            relief=tk.FLAT, bd=0, width=13,
        )
        self.aipic_input.pack(side=tk.LEFT, ipady=7, padx=(0, 4))
        self.aipic_input.bind("<Return>", lambda e: self._generate_ai_pic())
        mk_btn(r2, "Generate", self._generate_ai_pic, bg=C["amber"], padx=10).pack(side=tk.LEFT, ipady=7, padx=(0, 12))

        # Bot
        tk.Label(r2, text="Bot", bg=C["bg_panel"], fg=C["txt_muted"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 3))
        self.bot_input = tk.Entry(
            r2, font=("Segoe UI", 11),
            bg=C["bg_input"], fg=C["txt_main"],
            insertbackground=C["txt_main"],
            relief=tk.FLAT, bd=0, width=13,
        )
        self.bot_input.pack(side=tk.LEFT, ipady=7, padx=(0, 4))
        self.bot_input.bind("<Return>", lambda e: self._ask_bot())
        mk_btn(r2, "Ask 🤖", self._ask_bot, bg=C["purple"], padx=10).pack(side=tk.LEFT, ipady=7)

    # ── + Menu toggle ─────────────────────────────────────────────────────────

    def _toggle_menu(self):
        if self._menu_visible:
            self._menu_frame.pack_forget()
            self._plus_btn.config(text="+")
            self._menu_visible = False
        else:
            # Place just above the separator (which is above the panel)
            slaves = self.root.pack_slaves()
            sep_index = slaves.index(self.root.pack_slaves()[-2])
            self._menu_frame.pack(fill=tk.X, before=slaves[-2])
            self._plus_btn.config(text="✕")
            self._menu_visible = True

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self):
        name = simpledialog.askstring("Login", "Enter your username:", parent=self.root)
        if not name:
            self.root.destroy()
            return
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.connect(SERVER)
            mysend(self.s, json.dumps({"action": "login", "name": name}))
            resp = json.loads(myrecv(self.s))
            if resp["status"] == "ok":
                self.me = name
                self._append("system", f"Welcome, {name}! Press + for commands.\n")
                self._append("system", "Tips: /aipic: <prompt>  |  /summary  |  /keywords\n")
                self._update_status()
                self.running = True
                threading.Thread(target=self._recv_loop, daemon=True).start()
                self.root.after(100, self._process_queue)
            elif resp["status"] == "duplicate":
                messagebox.showerror("Login Failed", "Username already taken!")
                self.root.destroy()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.root.destroy()

    # ── Network ───────────────────────────────────────────────────────────────

    def _recv_loop(self):
        import select
        while self.running:
            try:
                read, _, _ = select.select([self.s], [], [], 0.2)
                if self.s in read:
                    raw = myrecv(self.s)
                    if raw:
                        msg = json.loads(raw)
                        action = msg.get("action")
                        if (action in ("exchange", "disconnect") or
                                (action == "connect" and msg.get("status") == "request")):
                            self.msg_queue.put(raw)
                        else:
                            self.response_queue.put(raw)
            except:
                break

    def _send_cmd(self, action_json):
        try:
            with self.sock_lock:
                mysend(self.s, action_json)
            resp = self.response_queue.get(timeout=5)
            return json.loads(resp)
        except Exception:
            return {"results": "", "status": "error"}

    def _process_queue(self):
        while not self.msg_queue.empty():
            raw = self.msg_queue.get()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "exchange":
                    text = msg.get("message", "")
                    sender = msg.get("from", "peer")
                    self._append("peer", f"{sender}: {text}  {get_sentiment(text)}\n")
                    self.chat_history.append(text)
                elif action == "connect":
                    self.peer = msg.get("from", "")
                    self.state = S_CHATTING
                    self._append("system", f"Request from {self.peer}\n")
                    self._append("system", f"Connected with {self.peer}. Chat away!\n")
                    self._update_status()
                elif action == "disconnect":
                    self._append("system", msg.get("msg", "Peer disconnected") + "\n")
                    self.state = S_LOGGEDIN
                    self.peer = ""
                    self._update_status()
            except Exception as e:
                self._append("system", f"Error: {e}\n")
        if self.running:
            self.root.after(100, self._process_queue)

    # ── Send message ──────────────────────────────────────────────────────────

    def _send_message(self):
        msg = self.msg_input.get().strip()
        if not msg:
            return
        self.msg_input.delete(0, tk.END)

        if msg.lower().startswith("/aipic:"):
            prompt = msg[7:].strip()
            if prompt:
                self.aipic_input.delete(0, tk.END)
                self.aipic_input.insert(0, prompt)
                self._generate_ai_pic()
            else:
                self._append("system", "Usage: /aipic: <your prompt>\n")
            return
        if msg.lower() == "/summary":
            self._nlp_summary(); return
        if msg.lower() == "/keywords":
            self._nlp_keywords(); return

        if self.state == S_CHATTING:
            self._append("me", f"[{self.me}]: {msg}  {get_sentiment(msg)}\n")
            self.chat_history.append(msg)
            with self.sock_lock:
                mysend(self.s, json.dumps({"action": "exchange", "from": f"[{self.me}]", "message": msg}))
            if msg == "bye":
                with self.sock_lock:
                    mysend(self.s, json.dumps({"action": "disconnect"}))
                time.sleep(0.2)
                self.state = S_LOGGEDIN
                self.peer = ""
                self._update_status()

        elif msg.startswith("?"):
            term = msg[1:].strip()
            try:
                resp = self._send_cmd(json.dumps({"action": "search", "target": term}))
                result = resp.get("results", "").strip()
                self._append("system", result + "\n" if result else f"'{term}' not found\n")
            except:
                self._append("system", f"'{term}' not found\n")

        elif msg.startswith("p") and msg[1:].isdigit():
            try:
                resp = self._send_cmd(json.dumps({"action": "poem", "target": msg[1:]}))
                poem = resp.get("results", "").strip()
                self._append("system", poem + "\n" if poem else f"Sonnet {msg[1:]} not found.\n")
            except:
                self._append("system", f"Sonnet {msg[1:]} not found.\n")
        else:
            self._append("system",
                "?term → search  |  p# → sonnet  |  /aipic: prompt  |  /summary  |  /keywords\n")

    # ── Utility actions ───────────────────────────────────────────────────────

    def _who(self):
        resp = self._send_cmd(json.dumps({"action": "list"}))
        self._append("system", "Online:\n" + resp.get("results", "") + "\n")

    def _time(self):
        resp = self._send_cmd(json.dumps({"action": "time"}))
        self._append("system", "Time: " + resp.get("results", "") + "\n")

    def _connect_peer(self):
        peer = simpledialog.askstring("Connect", "Username to connect to:", parent=self.root)
        if not peer:
            return
        resp = self._send_cmd(json.dumps({"action": "connect", "target": peer}))
        s = resp.get("status", "")
        if s == "success":
            self.peer = peer; self.state = S_CHATTING
            self._append("system", f"Connected to {peer}. Chat away!\n")
            self._update_status()
        elif s == "self":
            self._append("system", "Cannot connect to yourself!\n")
        elif s == "busy":
            self._append("system", "User is busy.\n")
        else:
            self._append("system", "User not online.\n")

    def _clear_chat(self):
        """Clears all messages from the chat display. Generated with pi-mono."""
        self.chat_display.config(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.config(state="disabled")

    def _disconnect_peer(self):
        if self.state == S_CHATTING:
            with self.sock_lock:
                mysend(self.s, json.dumps({"action": "disconnect"}))
            self._append("system", f"Disconnected from {self.peer}.\n")
            self.state = S_LOGGEDIN; self.peer = ""
            self._update_status()
        else:
            self._append("system", "Not currently chatting.\n")

    # ── Chatbot ───────────────────────────────────────────────────────────────

    def _ask_bot(self):
        msg = self.bot_input.get().strip()
        if not msg:
            return
        self.bot_input.delete(0, tk.END)
        self._append("me", f"[You → Bot]: {msg}\n")
        self._append("system", "Bot is thinking…\n")

        def run():
            try:
                reply = self.bot.chat(msg)
                self.root.after(0, self._append, "bot", f"[Bot]: {reply}\n")
            except Exception as e:
                self.root.after(0, self._append, "system", f"Bot error: {e}\n")

        threading.Thread(target=run, daemon=True).start()

    # ── NLP ───────────────────────────────────────────────────────────────────

    def _nlp_summary(self):
        if not self.chat_history:
            self._append("nlp", "📝 No chat history yet.\n"); return
        self._append("nlp", f"📝 Summary:\n{generate_summary(self.chat_history)}\n")

    def _nlp_keywords(self):
        if not self.chat_history:
            self._append("nlp", "🔑 No chat history yet.\n"); return
        kws = extract_keywords(self.chat_history)
        if not kws:
            self._append("nlp", "🔑 No keywords found.\n"); return
        self._append("nlp", "🔑 Keywords: " + "  ".join(f"{w}({c})" for w, c in kws) + "\n")

    # ── AI Pic ────────────────────────────────────────────────────────────────

    def _generate_ai_pic(self):
        prompt = self.aipic_input.get().strip()
        if not prompt:
            self._append("aipic", "🎨 Enter a prompt first.\n"); return
        self.aipic_input.delete(0, tk.END)
        if not PIL_OK:
            self._append("aipic", "🎨 Install Pillow: pip install Pillow\n"); return
        self._append("aipic", f"🎨 Generating \"{prompt}\"…\n")

        def run():
            photo, err = fetch_ai_image(prompt)
            if err:
                self.root.after(0, self._append, "aipic", f"🎨 Failed: {err}\n")
                return
            def show():
                self._image_refs.append(photo)
                self.chat_display.config(state="normal")
                self.chat_display.insert(tk.END, f"🎨 \"{prompt}\":\n", "aipic")
                self.chat_display.image_create(tk.END, image=photo)
                self.chat_display.insert(tk.END, "\n\n")
                self.chat_display.config(state="disabled")
                self.chat_display.see(tk.END)
            self.root.after(0, show)

        threading.Thread(target=run, daemon=True).start()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _append(self, tag, msg):
        self.chat_display.config(state="normal")
        self.chat_display.insert(tk.END, msg if msg.endswith("\n") else msg + "\n", tag)
        self.chat_display.config(state="disabled")
        self.chat_display.see(tk.END)

    def _update_status(self):
        if self.state == S_CHATTING:
            self.status_var.set(f"  {self.me}  ·  chatting with {self.peer}")
        else:
            self.status_var.set(f"  {self.me}  ·  idle")


def main():
    root = tk.Tk()
    ChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()