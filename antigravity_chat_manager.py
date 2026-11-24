"""
Antigravity Chat Manager & Rollback Tool
Графический интерфейс для быстрого просмотра, редактирования мыслей и отката сессий Google Antigravity.
Оптимизирован для плавной работы без лагов даже на 1000+ сообщениях.
"""

import os
import sys
import json
import shutil
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

BRAIN_DIR = os.path.expanduser(r"~\.gemini\antigravity\brain")
CHUNK_SIZE = 102400  # 100 KB chunks used by Antigravity
DEFAULT_PAGE_SIZE = 35


def clean_preview_text(text: str, max_len: int = 65) -> str:
    if not text:
        return "(Пустой запрос)"
    text = text.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("<") and not line.startswith("#"):
            if len(line) > max_len:
                return line[:max_len] + "..."
            return line
    return text[:max_len].strip() or "(Без текста)"


def get_chat_sessions():
    sessions = []
    if not os.path.exists(BRAIN_DIR):
        return sessions

    for entry in os.listdir(BRAIN_DIR):
        full_path = os.path.join(BRAIN_DIR, entry)
        if not os.path.isdir(full_path):
            continue

        full_log = os.path.join(full_path, ".system_generated", "logs", "transcript_full.jsonl")
        compact_log = os.path.join(full_path, ".system_generated", "logs", "transcript.jsonl")

        if not os.path.exists(full_log):
            continue

        mtime = os.path.getmtime(full_log)
        dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")

        title = "Новый диалог"
        step_count = 0
        try:
            with open(compact_log, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    step_count += 1
                    if title == "Новый диалог":
                        try:
                            obj = json.loads(line)
                            if obj.get("source") == "USER_EXPLICIT" or obj.get("type") == "USER_INPUT":
                                c = obj.get("content", "")
                                if c:
                                    title = clean_preview_text(c)
                        except:
                            pass
        except Exception:
            pass

        sessions.append({
            "id": entry,
            "path": full_path,
            "full_log": full_log,
            "compact_log": compact_log,
            "mtime": mtime,
            "dt_str": dt_str,
            "title": title,
            "steps": step_count
        })

    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def update_chunks(log_path: str, chunk_dir: str):
    if os.path.exists(chunk_dir):
        shutil.rmtree(chunk_dir, ignore_errors=True)
    os.makedirs(chunk_dir, exist_ok=True)

    if not os.path.exists(log_path):
        return

    with open(log_path, "rb") as src:
        chunk_idx = 0
        while True:
            block = src.read(CHUNK_SIZE)
            if not block:
                break
            chunk_name = f"{chunk_idx:08d}.jsonl"
            with open(os.path.join(chunk_dir, chunk_name), "wb") as dst:
                dst.write(block)
            chunk_idx += 1


def backup_session(session_path: str):
    logs_dir = os.path.join(session_path, ".system_generated", "logs")
    bak_dir = os.path.join(logs_dir, "backups")
    os.makedirs(bak_dir, exist_ok=True)
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    for fname in ["transcript.jsonl", "transcript_full.jsonl"]:
        src = os.path.join(logs_dir, fname)
        if os.path.exists(src):
            dst = os.path.join(bak_dir, f"{fname}.bak_{now_str}")
            shutil.copy2(src, dst)


def save_session_records(session: dict, full_records: list):
    backup_session(session["path"])

    logs_dir = os.path.join(session["path"], ".system_generated", "logs")
    full_path = session["full_log"]
    compact_path = session["compact_log"]

    # Write full
    with open(full_path, "w", encoding="utf-8") as f:
        for r in full_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Generate compact version
    compact_records = []
    for r in full_records:
        cr = dict(r)
        if "content" in cr and isinstance(cr["content"], str) and len(cr["content"]) > 1000:
            if cr.get("type") == "GENERIC":
                cr["content"] = cr["content"][:800] + "\n... [truncated]"
                if "truncated_fields" not in cr:
                    cr["truncated_fields"] = ["content"]
        compact_records.append(cr)

    with open(compact_path, "w", encoding="utf-8") as f:
        for r in compact_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Update chunks
    update_chunks(full_path, os.path.join(logs_dir, "chunks", "transcript_full"))
    update_chunks(compact_path, os.path.join(logs_dir, "chunks", "transcript"))


class ChatManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Antigravity Chat & Thought Editor")
        self.geometry("1320x860")
        self.minsize(1020, 640)
        self.configure(bg="#181825")

        self.sessions = []
        self.current_session = None
        self.full_records = []
        self.visible_limit = DEFAULT_PAGE_SIZE

        self._init_styles()
        self._build_ui()
        self.refresh_session_list()

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Treeview",
                        background="#1e1e2e",
                        foreground="#cdd6f4",
                        fieldbackground="#1e1e2e",
                        rowheight=28,
                        font=("Segoe UI", 9))
        style.map("Treeview",
                  background=[("selected", "#45475a")],
                  foreground=[("selected", "#ffffff")])

        style.configure("Treeview.Heading",
                        background="#313244",
                        foreground="#cdd6f4",
                        font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        header = tk.Frame(self, bg="#11111b", height=42)
        header.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(header, text="🧠 Antigravity Chat & Thought Editor",
                             bg="#11111b", fg="#cba6f7", font=("Segoe UI", 12, "bold"))
        title_lbl.pack(side=tk.LEFT, padx=15, pady=8)

        hint_lbl = tk.Label(header, text="💡 После отката нажмите в Antigravity: Ctrl+Shift+P -> 'Developer: Reload Window'",
                            bg="#11111b", fg="#a6adc8", font=("Segoe UI", 9))
        hint_lbl.pack(side=tk.RIGHT, padx=15, pady=8)

        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#181825", sashwidth=4, bd=0)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left panel: Session list
        left_frame = tk.Frame(paned, bg="#1e1e2e", width=400)
        paned.add(left_frame, minsize=300)

        search_box = tk.Frame(left_frame, bg="#1e1e2e")
        search_box.pack(fill=tk.X, padx=10, pady=8)

        self.search_var = tk.StringVar()
        if hasattr(self.search_var, "trace_add"):
            self.search_var.trace_add("write", lambda *args: self.filter_sessions())
        else:
            self.search_var.trace("w", lambda *args: self.filter_sessions())

        search_entry = tk.Entry(search_box, textvariable=self.search_var, bg="#313244", fg="#cdd6f4",
                                insertbackground="#cdd6f4", font=("Segoe UI", 10), bd=0, relief=tk.FLAT)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 6))

        refresh_btn = tk.Button(search_box, text="🔄", bg="#45475a", fg="#ffffff", activebackground="#585b70",
                                bd=0, font=("Segoe UI", 10), cursor="hand2", command=self.refresh_session_list)
        refresh_btn.pack(side=tk.RIGHT, ipadx=6, ipady=2)

        tree_frame = tk.Frame(left_frame, bg="#1e1e2e")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        cols = ("title", "date", "steps")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("title", text="Чат / Тема")
        self.tree.heading("date", text="Дата")
        self.tree.heading("steps", text="Шагов")

        self.tree.column("title", width=220, anchor="w")
        self.tree.column("date", width=110, anchor="center")
        self.tree.column("steps", width=55, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_session_selected)

        # Right panel: Timeline
        self.right_frame = tk.Frame(paned, bg="#181825")
        paned.add(self.right_frame, minsize=600)

        self.session_bar = tk.Frame(self.right_frame, bg="#1e1e2e", height=45)
        self.session_bar.pack(fill=tk.X, padx=0, pady=(0, 6))

        self.session_title_lbl = tk.Label(self.session_bar, text="Выберите чат слева",
                                          bg="#1e1e2e", fg="#cdd6f4", font=("Segoe UI", 11, "bold"))
        self.session_title_lbl.pack(side=tk.LEFT, padx=12, pady=10)

        self.session_info_lbl = tk.Label(self.session_bar, text="",
                                         bg="#1e1e2e", fg="#a6adc8", font=("Segoe UI", 9))
        self.session_info_lbl.pack(side=tk.RIGHT, padx=12, pady=10)

        # Canvas with mousewheel support
        self.canvas = tk.Canvas(self.right_frame, bg="#181825", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.right_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.timeline_frame = tk.Frame(self.canvas, bg="#181825")

        self.timeline_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.timeline_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        # Fast, responsive mousewheel scrolling
        self.canvas.yview_scroll(int(-1 * (event.delta / 40)), "units")

    def refresh_session_list(self):
        self.sessions = get_chat_sessions()
        self.filter_sessions()

    def filter_sessions(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        q = self.search_var.get().lower().strip()
        for idx, s in enumerate(self.sessions):
            if not q or q in s["title"].lower() or q in s["id"].lower():
                self.tree.insert("", tk.END, iid=str(idx), values=(s["title"], s["dt_str"], s["steps"]))

    def on_session_selected(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self.current_session = self.sessions[idx]
        self.visible_limit = DEFAULT_PAGE_SIZE
        self.load_session_timeline()

    def load_session_timeline(self):
        for w in self.timeline_frame.winfo_children():
            w.destroy()

        s = self.current_session
        self.session_title_lbl.config(text=f"💬 {s['title']}")
        self.session_info_lbl.config(text=f"ID: {s['id'][:12]}... | Всего шагов: {s['steps']}")

        self.full_records = []
        try:
            with open(s["full_log"], "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.full_records.append(json.loads(line))
                        except:
                            pass
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать логи: {e}")
            return

        total_steps = len(self.full_records)
        if total_steps == 0:
            tk.Label(self.timeline_frame, text="Чат пуст", bg="#181825", fg="#a6adc8").pack(pady=40)
            return

        # Lazy loading banner: show only last N steps by default
        start_idx = max(0, total_steps - self.visible_limit)
        if start_idx > 0:
            load_box = tk.Frame(self.timeline_frame, bg="#1e1e2e", bd=1, relief=tk.SOLID)
            load_box.pack(fill=tk.X, padx=10, pady=8)

            msg_lbl = tk.Label(load_box,
                               text=f"Скрыто более ранних шагов: {start_idx} (показаны последние {total_steps - start_idx} из {total_steps})",
                               bg="#1e1e2e", fg="#a6adc8", font=("Segoe UI", 9))
            msg_lbl.pack(side=tk.LEFT, padx=12, pady=6)

            btn_all = tk.Button(load_box, text="⏩ Показать все шаги", bg="#313244", fg="#cdd6f4",
                                font=("Segoe UI", 8), bd=0, cursor="hand2", padx=8, pady=3,
                                command=self.show_all_steps)
            btn_all.pack(side=tk.RIGHT, padx=6, pady=6)

            btn_more = tk.Button(load_box, text=f"⬆️ Загрузить еще 40 шагов", bg="#45475a", fg="#ffffff",
                                 font=("Segoe UI", 8, "bold"), bd=0, cursor="hand2", padx=8, pady=3,
                                 command=self.load_more_steps)
            btn_more.pack(side=tk.RIGHT, padx=6, pady=6)

        # Render visible slice
        for row_idx in range(start_idx, total_steps):
            is_last = (row_idx == total_steps - 1)
            self._render_step_card(row_idx, self.full_records[row_idx], auto_expand=is_last)

        # Scroll to bottom
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def load_more_steps(self):
        self.visible_limit += 40
        self.load_session_timeline()

    def show_all_steps(self):
        self.visible_limit = len(self.full_records) + 10
        self.load_session_timeline()

    def _render_step_card(self, row_idx: int, record: dict, auto_expand: bool = False):
        step_idx = record.get("step_index", row_idx)
        src = record.get("source", "UNKNOWN")
        rec_type = record.get("type", "GENERIC")
        created = record.get("created_at", "")[:19].replace("T", " ")

        card = tk.Frame(self.timeline_frame, bg="#24273a", bd=1, relief=tk.SOLID)
        card.pack(fill=tk.X, padx=10, pady=5, expand=True)

        header = tk.Frame(card, bg="#1e2030")
        header.pack(fill=tk.X, side=tk.TOP)

        if src == "USER_EXPLICIT" or rec_type == "USER_INPUT":
            badge_bg, badge_fg, badge_text = "#a6e3a1", "#11111b", "👤 USER"
        elif rec_type == "PLANNER_RESPONSE":
            badge_bg, badge_fg, badge_text = "#cba6f7", "#11111b", "🤖 ASSISTANT"
        elif rec_type == "CHECKPOINT":
            badge_bg, badge_fg, badge_text = "#f9e2af", "#11111b", "📌 CHECKPOINT"
        else:
            badge_bg, badge_fg, badge_text = "#89b4fa", "#11111b", f"⚙️ {rec_type}"

        tk.Label(header, text=badge_text, bg=badge_bg, fg=badge_fg,
                 font=("Segoe UI", 8, "bold"), padx=6, pady=2).pack(side=tk.LEFT, padx=8, pady=4)

        tk.Label(header, text=f"Шаг #{step_idx} | {created}", bg="#1e2030", fg="#a6adc8",
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=6)

        btn_frame = tk.Frame(header, bg="#1e2030")
        btn_frame.pack(side=tk.RIGHT, padx=6)

        edit_btn = tk.Button(btn_frame, text="✏️ Изменить", bg="#363a4f", fg="#cad3f5",
                             font=("Segoe UI", 8), bd=0, cursor="hand2", padx=6, pady=1,
                             command=lambda idx=row_idx: self.edit_record_dialog(idx))
        edit_btn.pack(side=tk.LEFT, padx=3)

        rb_btn = tk.Button(btn_frame, text="⏮️ Откатить досюда", bg="#ed8796", fg="#181926",
                           font=("Segoe UI", 8, "bold"), bd=0, cursor="hand2", padx=6, pady=1,
                           command=lambda idx=row_idx: self.rollback_to_index(idx))
        rb_btn.pack(side=tk.LEFT, padx=3)

        del_btn = tk.Button(btn_frame, text="❌", bg="#493843", fg="#ee99a0",
                            font=("Segoe UI", 8), bd=0, cursor="hand2", padx=5, pady=1,
                            command=lambda idx=row_idx: self.delete_single_record(idx))
        del_btn.pack(side=tk.LEFT, padx=3)

        body = tk.Frame(card, bg="#24273a")
        body.pack(fill=tk.BOTH, padx=10, pady=6, expand=True)

        # Collapsible Thinking Block (Lightweight & Super Fast)
        thinking = record.get("thinking")
        if thinking:
            th_container = tk.Frame(body, bg="#181926", bd=1, relief=tk.GROOVE)
            th_container.pack(fill=tk.X, pady=(0, 4))

            th_head = tk.Frame(th_container, bg="#181926")
            th_head.pack(fill=tk.X)

            th_body_frame = tk.Frame(th_container, bg="#11111b")

            def toggle_thinking(b_frame=th_body_frame, th_str=thinking, b_btn=None):
                if b_frame.winfo_ismapped():
                    b_frame.pack_forget()
                    if b_btn:
                        b_btn.config(text=f"▶ 💭 Показать мысли модели ({len(th_str)} симв.)")
                else:
                    if not b_frame.winfo_children():
                        # Lazy create text widget only on expand
                        txt = tk.Text(b_frame, wrap=tk.WORD, height=min(8, max(3, th_str.count("\n") + 1)),
                                      bg="#11111b", fg="#eed49f", insertbackground="#eed49f",
                                      font=("Consolas", 8), bd=0, relief=tk.FLAT)
                        txt.insert(tk.END, th_str)
                        txt.config(state=tk.DISABLED)
                        txt.pack(fill=tk.X, padx=6, pady=6)
                    b_frame.pack(fill=tk.X)
                    if b_btn:
                        b_btn.config(text=f"▼ 💭 Скрыть мысли модели ({len(th_str)} симв.)")

            toggle_btn = tk.Button(th_head, text=f"▶ 💭 Показать мысли модели ({len(thinking)} симв.)",
                                   bg="#181926", fg="#f5a97f", activebackground="#24273a", activeforeground="#f5a97f",
                                   font=("Segoe UI", 8, "bold"), bd=0, cursor="hand2", anchor="w")
            toggle_btn.config(command=lambda: toggle_thinking(th_body_frame, thinking, toggle_btn))
            toggle_btn.pack(side=tk.LEFT, padx=6, pady=3)

            # Auto expand thinking on the last step
            if auto_expand:
                toggle_thinking(th_body_frame, thinking, toggle_btn)

        # Tool calls
        tool_calls = record.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                t_name = tc.get("name", "tool")
                t_arg = tc.get("args", {})
                arg_preview = t_arg.get("Path") or t_arg.get("CommandLine") or str(t_arg)[:80]
                tk.Label(body, text=f"🔧 Вызов: {t_name} -> {arg_preview}",
                         bg="#24273a", fg="#8aadf4", font=("Segoe UI", 8, "italic")).pack(anchor="w", pady=1)

        # Content (Fast Flat Text Widget)
        content = record.get("content")
        if content:
            is_blocked = "blocked by Gemini's filters" in str(content)
            txt_color = "#ed8796" if is_blocked else "#cad3f5"
            bg_color = "#36222b" if is_blocked else "#1e2030"

            line_cnt = min(8, max(1, str(content).count("\n") + 1))
            c_txt = tk.Text(body, wrap=tk.WORD, height=line_cnt, bg=bg_color, fg=txt_color,
                            insertbackground="#cad3f5", font=("Segoe UI", 9), bd=0, relief=tk.FLAT)
            c_txt.insert(tk.END, str(content))
            c_txt.config(state=tk.DISABLED)
            c_txt.pack(fill=tk.X, pady=(2, 0))

    def rollback_to_index(self, target_row_idx: int):
        total = len(self.full_records)
        to_delete = total - (target_row_idx + 1)
        if to_delete <= 0:
            messagebox.showinfo("Инфо", "Это и так последний шаг в чате.")
            return

        step_num = self.full_records[target_row_idx].get("step_index", target_row_idx)
        msg = (f"Вы действительно хотите откатить чат до шага #{step_num}?\n\n"
               f"Будет удалено шагов после него: {to_delete}.\n"
               f"Перед откатом будет автоматически создана резервная копия.")

        if not messagebox.askyesno("Подтверждение отката", msg):
            return

        new_records = self.full_records[:target_row_idx + 1]
        try:
            save_session_records(self.current_session, new_records)
            messagebox.showinfo(
                "Успех!",
                f"Чат успешно откатан!\n\n"
                f"Удалено шагов: {to_delete}.\n"
                f"Бэкап сохранен в .system_generated/logs/backups/\n\n"
                f"👉 Чтобы обновить открытый чат в Antigravity, нажмите:\n"
                f"Ctrl+Shift+P -> 'Developer: Reload Window'"
            )
            self.refresh_session_list()
            self.load_session_timeline()
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить изменения: {e}")

    def delete_single_record(self, row_idx: int):
        rec = self.full_records[row_idx]
        step_idx = rec.get("step_index", row_idx)

        if not messagebox.askyesno("Удаление шага", f"Удалить только шаг #{step_idx} (запись {row_idx})?"):
            return

        new_records = list(self.full_records)
        new_records.pop(row_idx)
        try:
            save_session_records(self.current_session, new_records)
            messagebox.showinfo("Успех", f"Шаг #{step_idx} удален! Не забудьте Reload Window в Antigravity.")
            self.refresh_session_list()
            self.load_session_timeline()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить шаг: {e}")

    def edit_record_dialog(self, row_idx: int):
        rec = self.full_records[row_idx]
        step_idx = rec.get("step_index", row_idx)

        dialog = tk.Toplevel(self)
        dialog.title(f"Редактирование шага #{step_idx}")
        dialog.geometry("750x620")
        dialog.configure(bg="#181825")
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text=f"Редактирование шага #{step_idx} ({rec.get('source')})",
                 bg="#181825", fg="#cba6f7", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=15, pady=8)

        # Thinking editor
        tk.Label(dialog, text="💭 Мысли модели (Thinking):", bg="#181825", fg="#f5a97f",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15)
        th_edit = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, height=10, bg="#11111b", fg="#eed49f",
                                            insertbackground="#eed49f", font=("Consolas", 9), bd=0)
        th_edit.insert(tk.END, rec.get("thinking") or "")
        th_edit.pack(fill=tk.BOTH, expand=True, padx=15, pady=(2, 10))

        # Content editor
        tk.Label(dialog, text="📄 Содержимое ответа / запроса (Content):", bg="#181825", fg="#cad3f5",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15)
        c_edit = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, height=10, bg="#1e2030", fg="#cad3f5",
                                           insertbackground="#cad3f5", font=("Segoe UI", 9), bd=0)
        c_edit.insert(tk.END, str(rec.get("content") or ""))
        c_edit.pack(fill=tk.BOTH, expand=True, padx=15, pady=(2, 15))

        btn_box = tk.Frame(dialog, bg="#181825")
        btn_box.pack(fill=tk.X, padx=15, pady=(0, 15))

        def save_edits():
            new_th = th_edit.get("1.0", tk.END).rstrip("\n")
            new_c = c_edit.get("1.0", tk.END).rstrip("\n")

            if new_th:
                rec["thinking"] = new_th
            elif "thinking" in rec:
                del rec["thinking"]

            rec["content"] = new_c

            try:
                save_session_records(self.current_session, self.full_records)
                dialog.destroy()
                messagebox.showinfo("Сохранено", "Шаг успешно изменен! Не забудьте перезагрузить окно в Antigravity.")
                self.load_session_timeline()
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

        tk.Button(btn_box, text="💾 Сохранить изменения", bg="#a6e3a1", fg="#11111b",
                  font=("Segoe UI", 9, "bold"), bd=0, padx=12, pady=5, cursor="hand2",
                  command=save_edits).pack(side=tk.RIGHT, padx=5)

        tk.Button(btn_box, text="Отмена", bg="#363a4f", fg="#cad3f5",
                  font=("Segoe UI", 9), bd=0, padx=12, pady=5, cursor="hand2",
                  command=dialog.destroy).pack(side=tk.RIGHT)


if __name__ == "__main__":
    app = ChatManagerApp()
    app.mainloop()
