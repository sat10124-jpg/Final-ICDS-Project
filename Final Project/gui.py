#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py - Extended Chat GUI
Built on top of the provided GUI template.
Bug fix: self.system_msg now uses = instead of += to prevent message duplication.
Added features: sentiment analysis, chatbot, clear chat, status bar, color-coded messages.
"""

import threading
import select
import time
import json
import queue
import socket as sock_module
import urllib.request
import urllib.parse
import io
import tkinter as tk
from tkinter import font, ttk, simpledialog, messagebox, scrolledtext
from PIL import Image, ImageTk
from chat_utils import *
from client_state_machine import ClientSM
from chat_bot_client import ChatBotClient
from textblob import TextBlob
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from collections import Counter


def get_sentiment(text):
    """Returns sentiment emoji label for a given text string.
    Generated with pi-mono assistance."""
    polarity = TextBlob(text).sentiment.polarity
    if polarity > 0.1:
        return "😊 Positive"
    elif polarity < -0.1:
        return "😡 Negative"
    else:
        return "😐 Neutral"


def clear_chat(text_widget):
    """Clears all text from a tkinter Text widget.
    Generated with pi-mono assistance."""
    text_widget.config(state=tk.NORMAL)
    text_widget.delete('1.0', tk.END)
    text_widget.config(state=tk.DISABLED)


def extract_keywords(messages, top_n=8):
    """Extract top keywords from a list of chat messages using NLTK."""
    stop_words = set(stopwords.words('english'))
    # Add chat-specific stop words
    stop_words.update(['bye', 'hello', 'hi', 'hey', 'ok', 'okay', 'yes', 'no', 'lol'])
    all_words = []
    for msg in messages:
        tokens = word_tokenize(msg.lower())
        words = [w for w in tokens if w.isalpha() and w not in stop_words and len(w) > 2]
        all_words.extend(words)
    if not all_words:
        return []
    return Counter(all_words).most_common(top_n)


def generate_summary(messages):
    """Generate a simple summary of chat messages using sentence scoring."""
    if not messages:
        return "No messages to summarize."
    stop_words = set(stopwords.words('english'))
    # Score each message by how many non-stop words it contains
    scored = []
    for msg in messages:
        tokens = word_tokenize(msg.lower())
        score = sum(1 for w in tokens if w.isalpha() and w not in stop_words)
        scored.append((score, msg))
    scored.sort(reverse=True)
    # Return top 3 most content-rich messages as summary
    top = [msg for _, msg in scored[:3]]
    return " | ".join(top)


def generate_image(prompt):
    """Generate an image using Pollinations AI (free, no API key needed).
    Returns a PIL Image object."""
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=400&height=400&nologo=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        image_data = response.read()
    return Image.open(io.BytesIO(image_data))


# States (mirroring chat_utils)
S_LOGGEDIN = 1
S_CHATTING = 2


class GUI:
    """Extended chat GUI built on the provided template.
    Key fix: system_msg uses = not += to prevent message duplication.
    """

    def __init__(self, send, recv, sm, s):
        self.Window = tk.Tk()
        self.Window.withdraw()
        self.send = send
        self.recv = recv
        self.sm = sm
        self.socket = s
        self.my_msg = ""
        self.system_msg = ""   # BUG FIX: will use = not += when updating
        self.bot = ChatBotClient(name="Bot", model="phi4-mini")
        self.chat_history = []  # stores all chat messages for NLP analysis

        # Two queues: peer pushes vs command responses
        self.msg_queue = queue.Queue()
        self.response_queue = queue.Queue()

    # ------------------------------------------------------------------
    # Login window (kept from original template)
    # ------------------------------------------------------------------
    def login(self):
        self.login_win = tk.Toplevel()
        self.login_win.title("Login")
        self.login_win.resizable(False, False)
        self.login_win.configure(width=400, height=300, bg="#1a1a2e")

        tk.Label(self.login_win, text="💬 Chat App",
                 justify=tk.CENTER, font=("Helvetica", 18, "bold"),
                 bg="#1a1a2e", fg="#e94560").place(relheight=0.2, relx=0.3, rely=0.05)

        tk.Label(self.login_win, text="Username:",
                 font=("Helvetica", 12), bg="#1a1a2e", fg="#eaeaea").place(
                 relheight=0.15, relx=0.1, rely=0.35)

        self.entryName = tk.Entry(self.login_win, font=("Helvetica", 13),
                                  bg="#16213e", fg="white",
                                  insertbackground="white", relief=tk.FLAT)
        self.entryName.place(relwidth=0.45, relheight=0.12,
                             relx=0.35, rely=0.35)
        self.entryName.focus()
        self.entryName.bind("<Return>", lambda e: self.goAhead(self.entryName.get()))

        tk.Button(self.login_win, text="CONNECT",
                  font=("Helvetica", 12, "bold"),
                  bg="#e94560", fg="white", relief=tk.FLAT, cursor="hand2",
                  command=lambda: self.goAhead(self.entryName.get())).place(
                  relx=0.35, rely=0.6, relwidth=0.3, relheight=0.12)

        self.Window.mainloop()

    def goAhead(self, name):
        if len(name) > 0:
            msg = json.dumps({"action": "login", "name": name})
            self.send(msg)
            response = json.loads(self.recv())
            if response["status"] == "ok":
                self.login_win.destroy()
                self.sm.set_state(S_LOGGEDIN)
                self.sm.set_myname(name)
                self.layout(name)
                self._append("system", f"Welcome, {name}! Use the buttons or type commands.\n")
                # Start background receive thread
                process = threading.Thread(target=self.proc)
                process.daemon = True
                process.start()
                # Start queue processor on main thread
                self.Window.after(100, self._process_queue)
            elif response["status"] == "duplicate":
                messagebox.showerror("Login Failed", "Username already taken!")

    # ------------------------------------------------------------------
    # Main layout (extended from original template)
    # ------------------------------------------------------------------
    def layout(self, name):
        self.name = name
        self.Window.deiconify()
        self.Window.title("Chat App")
        self.Window.resizable(False, False)
        self.Window.configure(width=520, height=650, bg="#1a1a2e")

        # Status bar
        self.status_var = tk.StringVar(value=f"Logged in as: {name}  |  Not chatting")
        tk.Label(self.Window, textvariable=self.status_var,
                 bg="#e94560", fg="white", font=("Helvetica", 9, "bold"),
                 anchor="w", padx=10).place(relwidth=1, relheight=0.05)

        # Chat display area
        self.textCons = tk.Text(self.Window, width=20, height=2,
                                bg="#16213e", fg="#eaeaea",
                                font=("Helvetica", 11),
                                padx=8, pady=8, cursor="arrow")
        self.textCons.place(relheight=0.62, relwidth=0.96,
                            relx=0.02, rely=0.06)

        # Color tags
        self.textCons.tag_config("me",     foreground="#4fc3f7", font=("Helvetica", 11, "bold"))
        self.textCons.tag_config("peer",   foreground="#ef9a9a", font=("Helvetica", 11, "bold"))
        self.textCons.tag_config("system", foreground="#aaaaaa", font=("Helvetica", 10, "italic"))
        self.textCons.tag_config("bot",    foreground="#ce93d8", font=("Helvetica", 11, "bold"))

        # Scrollbar
        scrollbar = tk.Scrollbar(self.textCons)
        scrollbar.place(relheight=1, relx=0.974)
        scrollbar.config(command=self.textCons.yview)
        self.textCons.config(state=tk.DISABLED, yscrollcommand=scrollbar.set)

        # Bottom panel
        bottom = tk.Frame(self.Window, bg="#0f3460")
        bottom.place(relwidth=1, rely=0.69, relheight=0.09)

        self.entryMsg = tk.Entry(bottom, bg="#16213e", fg="white",
                                 font=("Helvetica", 12),
                                 insertbackground="white", relief=tk.FLAT)
        self.entryMsg.place(relwidth=0.72, relheight=0.6,
                            relx=0.01, rely=0.2)
        self.entryMsg.focus()
        self.entryMsg.bind("<Return>", lambda e: self.sendButton(self.entryMsg.get()))

        tk.Button(bottom, text="Send", font=("Helvetica", 10, "bold"),
                  bg="#e94560", fg="white", relief=tk.FLAT, cursor="hand2",
                  command=lambda: self.sendButton(self.entryMsg.get())).place(
                  relx=0.75, rely=0.15, relwidth=0.23, relheight=0.65)

        # Button row
        btn_frame = tk.Frame(self.Window, bg="#1a1a2e")
        btn_frame.place(relwidth=1, rely=0.79, relheight=0.07)

        for label, cmd in [("Who's Online", self._who),
                            ("Connect",     self._connect_peer),
                            ("Time",        self._time),
                            ("Disconnect",  self._disconnect_peer),
                            ("Clear Chat",  self._clear_chat)]:
            tk.Button(btn_frame, text=label, font=("Helvetica", 8, "bold"),
                      bg="#0f3460", fg="white", relief=tk.FLAT,
                      cursor="hand2", padx=6, pady=4,
                      command=cmd).pack(side=tk.LEFT, padx=3, pady=6)

        # Chatbot bar
        bot_frame = tk.Frame(self.Window, bg="#1a1a2e")
        bot_frame.place(relwidth=1, rely=0.87, relheight=0.07)

        tk.Label(bot_frame, text="🤖", font=("Helvetica", 12),
                 bg="#1a1a2e", fg="#ce93d8").pack(side=tk.LEFT, padx=(8, 2))

        self.bot_input = tk.Entry(bot_frame, bg="#16213e", fg="white",
                                  font=("Helvetica", 11),
                                  insertbackground="white", relief=tk.FLAT)
        self.bot_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 4))
        self.bot_input.bind("<Return>", lambda e: self._ask_bot())

        tk.Button(bot_frame, text="Ask Bot", font=("Helvetica", 9, "bold"),
                  bg="#6a0dad", fg="white", relief=tk.FLAT, cursor="hand2",
                  command=self._ask_bot).pack(side=tk.LEFT, padx=(0, 8))

        # Tip label
        tk.Label(self.Window,
                 text="  ?term=search | p#=sonnet | /keywords | /summary | /aipic: prompt",
                 bg="#0f3460", fg="#aaaaaa", font=("Helvetica", 8),
                 anchor="w").place(relwidth=1, rely=0.94, relheight=0.04)

    # ------------------------------------------------------------------
    # proc() - background thread, receives messages and routes to queues
    # CORE BUG FIX: system_msg = ... not system_msg += ...
    # ------------------------------------------------------------------
    def proc(self):
        while True:
            try:
                read, _, _ = select.select([self.socket], [], [], 0.2)
                peer_msg = ""
                if self.socket in read:
                    raw = self.recv()
                    if raw:
                        try:
                            msg = json.loads(raw)
                            action = msg.get("action")
                            if (action in ("exchange", "disconnect") or
                                    (action == "connect" and msg.get("status") == "request")):
                                self.msg_queue.put(raw)
                            else:
                                self.response_queue.put(raw)
                        except:
                            self.msg_queue.put(raw)

                if len(self.my_msg) > 0:
                    # BUG FIX: use = not += so message is not repeated
                    self.system_msg = self.sm.proc(self.my_msg, peer_msg)
                    self.my_msg = ""
            except:
                break

    # ------------------------------------------------------------------
    # Process incoming peer messages from queue on main thread
    # ------------------------------------------------------------------
    def _process_queue(self):
        while not self.msg_queue.empty():
            raw = self.msg_queue.get()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "exchange":
                    text = msg.get("message", "")
                    sender = msg.get("from", "peer")
                    sentiment = get_sentiment(text)
                    self.chat_history.append(text)  # track for NLP
                    self._append("peer", f"{sender}: {text}  {sentiment}\n")
                elif action == "connect":
                    self.peer = msg.get("from", "")
                    self.sm.set_state(S_CHATTING)
                    self.sm.peer = self.peer
                    self._append("system", f"Request from {self.peer}\n")
                    self._append("system", f"Connected with {self.peer}. Chat away!\n")
                    self._update_status()
                elif action == "disconnect":
                    self._append("system", msg.get("msg", "Peer disconnected") + "\n")
                    self.sm.set_state(S_LOGGEDIN)
                    self.sm.peer = ""
                    self._update_status()
            except Exception as e:
                self._append("system", f"Error: {e}\n")
        self.Window.after(100, self._process_queue)

    # ------------------------------------------------------------------
    # Send button (from original template, extended)
    # ------------------------------------------------------------------
    def sendButton(self, msg):
        msg = msg.strip()
        if not msg:
            return
        self.textCons.config(state=tk.DISABLED)
        self.entryMsg.delete(0, tk.END)

        state = self.sm.get_state()

        if state == S_CHATTING:
            sentiment = get_sentiment(msg)
            self._append("me", f"[{self.sm.get_myname()}]: {msg}  {sentiment}\n")
            self.chat_history.append(msg)  # track for NLP
            mysend(self.socket, json.dumps({"action": "exchange",
                                            "from": f"[{self.sm.get_myname()}]",
                                            "message": msg}))
            if msg == "bye":
                mysend(self.socket, json.dumps({"action": "disconnect"}))
                self.sm.set_state(S_LOGGEDIN)
                self.sm.peer = ""
                self._update_status()

        elif msg.startswith("/aipic:"):
            prompt = msg[7:].strip()
            if not prompt:
                self._append("system", "Usage: /aipic: your image description\n")
            else:
                self._append("system", f"🎨 Generating image: '{prompt}'... please wait\n")
                def gen_image(p=prompt):
                    try:
                        img = generate_image(p)
                        self.Window.after(0, self._show_image, img, p)
                    except Exception as e:
                        self.Window.after(0, self._append, "system", f"Image error: {e}\n")
                threading.Thread(target=gen_image, daemon=True).start()

        elif msg == "/keywords":
            if not self.chat_history:
                self._append("system", "No chat history yet. Start chatting first!\n")
            else:
                keywords = extract_keywords(self.chat_history)
                if keywords:
                    result = "  🔑 Top Keywords:\n"
                    for word, count in keywords:
                        result += f"     {word}: {count}x\n"
                    self._append("system", result)
                else:
                    self._append("system", "Not enough words to extract keywords.\n")

        elif msg == "/summary":
            if not self.chat_history:
                self._append("system", "No chat history yet. Start chatting first!\n")
            else:
                summary = generate_summary(self.chat_history)
                self._append("system", f"  📝 Chat Summary:\n     {summary}\n")

        elif msg.startswith("?"):
            term = msg[1:].strip()
            mysend(self.socket, json.dumps({"action": "search", "target": term}))
            try:
                resp = json.loads(self.response_queue.get(timeout=5))
                result = resp.get("results", "").strip()
                self._append("system", result + "\n" if result else f"'{term}' not found\n")
            except:
                self._append("system", f"'{term}' not found\n")

        elif msg.startswith("p") and msg[1:].isdigit():
            mysend(self.socket, json.dumps({"action": "poem", "target": msg[1:]}))
            try:
                resp = json.loads(self.response_queue.get(timeout=5))
                poem = resp.get("results", "").strip()
                self._append("system", poem + "\n" if poem else f"Sonnet {msg[1:]} not found\n")
            except:
                self._append("system", f"Sonnet {msg[1:]} not found\n")

        else:
            self._append("system", "Type  ?term  to search  |  p#  to get a sonnet\n")

    # ------------------------------------------------------------------
    # Button commands
    # ------------------------------------------------------------------
    def _who(self):
        mysend(self.socket, json.dumps({"action": "list"}))
        try:
            resp = json.loads(self.response_queue.get(timeout=5))
            self._append("system", "Users online:\n" + resp["results"] + "\n")
        except:
            self._append("system", "Could not retrieve user list.\n")

    def _time(self):
        mysend(self.socket, json.dumps({"action": "time"}))
        try:
            resp = json.loads(self.response_queue.get(timeout=5))
            self._append("system", "Time is: " + resp["results"] + "\n")
        except:
            self._append("system", "Could not retrieve time.\n")

    def _connect_peer(self):
        peer = simpledialog.askstring("Connect", "Enter username to connect to:",
                                      parent=self.Window)
        if not peer:
            return
        mysend(self.socket, json.dumps({"action": "connect", "target": peer}))
        try:
            resp = json.loads(self.response_queue.get(timeout=5))
            if resp["status"] == "success":
                self.sm.set_state(S_CHATTING)
                self.sm.peer = peer
                self._append("system", f"Connected to {peer}. Chat away!\n")
                self._update_status()
            elif resp["status"] == "self":
                self._append("system", "Cannot connect to yourself!\n")
            elif resp["status"] == "busy":
                self._append("system", "User is busy, try again later.\n")
            else:
                self._append("system", "User is not online.\n")
        except:
            self._append("system", "Connection failed.\n")

    def _disconnect_peer(self):
        if self.sm.get_state() == S_CHATTING:
            mysend(self.socket, json.dumps({"action": "disconnect"}))
            self._append("system", f"Disconnected from {self.sm.peer}.\n")
            self.sm.set_state(S_LOGGEDIN)
            self.sm.peer = ""
            self._update_status()
        else:
            self._append("system", "You are not currently chatting.\n")

    def _show_image(self, img, prompt):
        """Display a generated image in a popup window."""
        popup = tk.Toplevel(self.Window)
        popup.title(f"AI Image: {prompt[:40]}")
        popup.configure(bg="#1a1a2e")
        tk.Label(popup, text=f"🎨 {prompt}", bg="#1a1a2e", fg="#ce93d8",
                 font=("Helvetica", 10, "italic"), wraplength=400).pack(pady=(10, 4))
        photo = ImageTk.PhotoImage(img)
        label = tk.Label(popup, image=photo, bg="#1a1a2e")
        label.image = photo  # keep reference
        label.pack(padx=10, pady=10)
        tk.Button(popup, text="Close", bg="#e94560", fg="white",
                  font=("Helvetica", 10, "bold"), relief=tk.FLAT,
                  command=popup.destroy).pack(pady=(0, 10))
        self._append("system", f"🎨 Image generated for: '{prompt}'\n")

    def _clear_chat(self):
        """Clears all messages from the chat display. Generated with pi-mono."""
        clear_chat(self.textCons)

    def _ask_bot(self):
        msg = self.bot_input.get().strip()
        if not msg:
            return
        self.bot_input.delete(0, tk.END)
        self._append("me", f"[You → Bot]: {msg}\n")
        self._append("system", "Bot is thinking...\n")

        def run():
            try:
                reply = self.bot.chat(msg)
                self.Window.after(0, self._append, "bot", f"[Bot]: {reply}\n")
            except Exception as e:
                self.Window.after(0, self._append, "system", f"Bot error: {e}\n")

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _append(self, tag, msg):
        self.textCons.config(state=tk.NORMAL)
        self.textCons.insert(tk.END, msg if msg.endswith("\n") else msg + "\n", tag)
        self.textCons.config(state=tk.DISABLED)
        self.textCons.see(tk.END)

    def _update_status(self):
        name = self.sm.get_myname()
        if self.sm.get_state() == S_CHATTING:
            self.status_var.set(f"Logged in as: {name}  |  Chatting with: {self.sm.peer}")
        else:
            self.status_var.set(f"Logged in as: {name}  |  Not chatting")

    def run(self):
        self.login()


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    s = sock_module.socket(sock_module.AF_INET, sock_module.SOCK_STREAM)
    s.connect(SERVER)
    g = GUI(
        send=lambda msg: mysend(s, msg),
        recv=lambda: myrecv(s),
        sm=ClientSM(s),
        s=s
    )
    g.run()