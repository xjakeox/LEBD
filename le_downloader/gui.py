"""The main window and the Delete Saves window."""
import os
import threading
from .common import APP_DIR, LOG_FILE, logger
from .let_fetch import FetchError, run_from_link
from .items import build_info, export, format_summary
from . import le_profile, maxroll
from .save_writer import SaveError, find_default_save_dir, list_character_saves, next_save_file_name, save_slot_numbers, write_character_save


# ----------------------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    # Own Windows app ID, so the taskbar shows our icon instead of grouping under Python
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LastEpochBuildDownloader.V1")
    except Exception:  # noqa  (not Windows)
        pass

    root = tk.Tk()
    root.title("Last Epoch Build Downloader - Season 5 - V1.0")
    icon_file = os.path.join(APP_DIR, "LastEpochBuildDownloader.ico")
    if os.path.isfile(icon_file):
        try:
            root.iconbitmap(default=icon_file)   # default=: popups and the Delete Saves window too
        except Exception:  # noqa
            logger.info("Could not set window icon from %s", icon_file)
    root.report_callback_exception = lambda t, v, tb: logger.error(
        "Error in window callback", exc_info=(t, v, tb))
    root.minsize(600, 300)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Build link (Last Epoch Tools planner or profile character, or Maxroll planner):").pack(anchor="w")
    row = ttk.Frame(frm)
    row.pack(fill="x", pady=(4, 8))
    link_var = tk.StringVar()
    entry = ttk.Entry(row, textvariable=link_var)
    entry.pack(side="left", fill="x", expand=True)
    go_btn = ttk.Button(row, text="Download Character")
    go_btn.pack(side="left", padx=(8, 0))

    # Where and under what name the new character save is written.
    form = ttk.Frame(frm)
    form.pack(fill="x", pady=(0, 8))
    form.columnconfigure(1, weight=1)
    name_var = tk.StringVar()
    save_dir_var = tk.StringVar(value=find_default_save_dir())
    file_name_var = tk.StringVar()
    ttk.Label(form, text="Character name:").grid(row=0, column=0, sticky="w", pady=2)
    ttk.Entry(form, textvariable=name_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
    ttk.Label(form, text="Saves folder:").grid(row=1, column=0, sticky="w", pady=2)
    save_dir_entry = ttk.Entry(form, textvariable=save_dir_var)
    save_dir_entry.grid(row=1, column=1, sticky="ew", pady=2)
    browse_btn = ttk.Button(form, text="Browse...")
    browse_btn.grid(row=1, column=2, padx=(8, 0), pady=2)
    ttk.Label(form, text="New save file:").grid(row=2, column=0, sticky="w", pady=2, padx=(0, 8))
    ttk.Entry(form, textvariable=file_name_var).grid(row=2, column=1, sticky="ew", pady=2)
    refresh_btn = ttk.Button(form, text="Next slot")
    refresh_btn.grid(row=2, column=2, padx=(8, 0), pady=2)
    save_note = tk.StringVar()
    ttk.Label(form, textvariable=save_note, foreground="gray").grid(
        row=3, column=1, columnspan=2, sticky="w")

    row2 = ttk.Frame(frm)
    row2.pack(fill="x", pady=(0, 8))
    manage_btn = ttk.Button(row2, text="Delete Saves...")
    manage_btn.pack(side="left")

    # Build summary and output log: hidden until the user opens them.
    status = tk.StringVar(value="Paste a link and press Enter.")
    status_label = ttk.Label(frm, textvariable=status)
    status_label.pack(side="bottom", anchor="w", pady=(6, 0))
    LOG_HEIGHT = 820   # window height while the log is open

    def collapsible(title, **pack_opts):
        """A "▸ title" button that shows/hides the frame it returns. Starts hidden."""
        header = ttk.Frame(frm)
        header.pack(fill="x")
        body = ttk.Frame(frm)
        state = {"open": False}

        def toggle(open_=None):
            state["open"] = (not state["open"]) if open_ is None else open_
            button.configure(text=("\u25be " if state["open"] else "\u25b8 ") + title)
            if state["open"]:
                body.pack(after=header, pady=(0, 8), **pack_opts)
            else:
                body.pack_forget()
            fit_window()
        button = ttk.Button(header, text="\u25b8 " + title, style="Toolbutton", command=toggle)
        button.pack(side="left", pady=(0, 4))
        body.toggle = toggle
        body.is_open = lambda: state["open"]
        return body

    # Build summary, filled in from the link (display only).
    build_section = collapsible("Build", fill="x")
    info = ttk.Frame(build_section, padding=8, relief="groove", borderwidth=2)
    info.pack(fill="x")
    for c in (1, 3):
        info.columnconfigure(c, weight=1)
    class_var, level_var = tk.StringVar(), tk.StringVar()
    spec_vars = [tk.StringVar() for _ in range(5)]
    hotbar_vars = [tk.StringVar() for _ in range(5)]

    def show(var, r, c, label):
        ttk.Label(info, text=label).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 12, 6), pady=1)
        ttk.Entry(info, textvariable=var, state="readonly").grid(row=r, column=c + 1, sticky="ew", pady=1)

    show(class_var, 0, 0, "Class:")
    show(level_var, 0, 2, "Level:")
    for n in range(5):
        show(spec_vars[n], n + 1, 0, "Specialized Skill %d:" % (n + 1))
        show(hotbar_vars[n], n + 1, 2, "Hotbar Skill %d:" % (n + 1) if n < 4 else "Right Click:")

    def fill_info(d):
        class_var.set(d["class"])
        level_var.set(d["level"])
        for var, v in zip(spec_vars, d["specialized"]):
            var.set(v)
        for var, v in zip(hotbar_vars, d["hotbar"]):
            var.set(v)

    # Output box with both scroll bars (lines don't wrap, so long affix rows scroll sideways).
    log_section = collapsible("Details / log", fill="both", expand=True)
    out_box = ttk.Frame(log_section, height=420)
    out_box.pack(fill="both", expand=True)
    out = tk.Text(out_box, font=("Consolas" if os.name == "nt" else "Menlo", 10), wrap="none")
    out_y = ttk.Scrollbar(out_box, orient="vertical", command=out.yview)
    out_x = ttk.Scrollbar(out_box, orient="horizontal", command=out.xview)
    out.configure(yscrollcommand=out_y.set, xscrollcommand=out_x.set)
    out.grid(row=0, column=0, sticky="nsew")
    out_y.grid(row=0, column=1, sticky="ns")
    out_x.grid(row=1, column=0, sticky="ew")
    out_box.rowconfigure(0, weight=1)
    out_box.columnconfigure(0, weight=1)
    out.configure(height=20)

    def fit_window():
        """Shrink to fit while the log is closed; give the log room while it is open."""
        root.update_idletasks()
        width = max(root.winfo_width(), 780) if root.winfo_ismapped() else 780
        if log_section.is_open():
            height = max(root.winfo_height() if root.winfo_ismapped() else 0, LOG_HEIGHT)
            root.minsize(600, 640)
        else:
            height = root.winfo_reqheight()
            root.minsize(600, height)
        root.geometry("%dx%d" % (width, height))

    def update_save_name(*_):
        folder = save_dir_var.get().strip()
        file_name_var.set(next_save_file_name(folder))
        if not folder:
            save_note.set("Saves folder not found automatically. Use Browse to pick it.")
        elif not os.path.isdir(folder):
            save_note.set("That folder does not exist.")
        else:
            slots = save_slot_numbers(folder)
            save_note.set("Existing save slots: %s" % (", ".join(map(str, slots)) if slots
                                                         else "none"))

    def on_browse():
        p = filedialog.askdirectory(title="Choose your Last Epoch Saves folder",
                                    initialdir=save_dir_var.get() or os.path.expanduser("~"))
        if p:
            save_dir_var.set(os.path.normpath(p))
            update_save_name()

    def open_delete_window():
        folder = save_dir_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Delete Saves", "Choose your Saves folder first.")
            return
        messagebox.showwarning(
            "Delete Saves",
            "Saves deleted here may not stay deleted. If Steam Cloud is on, Steam can download "
            "them again the next time the game starts.\n\n"
            "If a character comes back, delete it manually in game for it to stick.")
        win = tk.Toplevel(root)
        win.title("Delete Saves")
        win.geometry("640x420")
        win.transient(root)
        ttk.Label(win, text="Saves in: %s" % folder, padding=(10, 8, 10, 4)).pack(anchor="w")
        box = ttk.Frame(win, padding=(10, 0))
        box.pack(fill="both", expand=True)
        canvas = tk.Canvas(box, highlightthickness=0)
        bar = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        table = ttk.Frame(canvas)
        table.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=table, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        checks = []

        def fill():
            for w in table.winfo_children():
                w.destroy()
            checks.clear()
            for c, h in enumerate(("", "File name", "Character name", "Level", "Class")):
                ttk.Label(table, text=h, font=("TkDefaultFont", 9, "bold")).grid(
                    row=0, column=c, sticky="w", padx=6, pady=(0, 4))
            saves = list_character_saves(folder)
            if not saves:
                ttk.Label(table, text="No character saves found.").grid(row=1, column=1, columnspan=4,
                                                                        sticky="w", padx=6)
            for r, sv in enumerate(saves, 1):
                var = tk.BooleanVar()
                ttk.Checkbutton(table, variable=var).grid(row=r, column=0, padx=6)
                for c, key in enumerate(("file", "name", "level", "class"), 1):
                    ttk.Label(table, text=sv[key]).grid(row=r, column=c, sticky="w", padx=6, pady=1)
                checks.append((var, sv))

        def on_delete():
            chosen = [sv for var, sv in checks if var.get()]
            if not chosen:
                messagebox.showinfo("Delete Saves", "Tick one or more saves to delete.", parent=win)
                return
            lines = "\n".join("%s%s  -  %s, level %s %s" % (
                sv["file"], " (+ .bak)" if os.path.exists(sv["path"] + ".bak") else "",
                sv["name"], sv["level"], sv["class"]) for sv in chosen)
            if not messagebox.askyesno(
                    "Confirm delete", "Permanently delete %d save file%s?\n\n%s\n\nThis cannot be undone."
                    % (len(chosen), "" if len(chosen) == 1 else "s", lines), icon="warning", parent=win):
                return
            failed = []
            for sv in chosen:
                # The game restores a save from its .bak on the next launch, so remove both.
                for path in (sv["path"], sv["path"] + ".bak"):
                    if path != sv["path"] and not os.path.exists(path):
                        continue
                    try:
                        os.remove(path)
                        logger.info("Deleted %s (%s)", path, sv["name"])
                    except OSError as e:
                        logger.exception("Could not delete %s", path)
                        failed.append("%s: %s" % (os.path.basename(path), e))
            fill()
            update_save_name()
            if failed:
                messagebox.showerror("Delete Saves", "Some files were not deleted:\n\n" + "\n".join(failed),
                                     parent=win)
            else:
                messagebox.showinfo("Delete Saves", "Deleted %d save file%s."
                                    % (len(chosen), "" if len(chosen) == 1 else "s"), parent=win)

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Delete", command=on_delete).pack(side="right", padx=(0, 8))
        fill()

    def save_settings():
        return {"character_name": name_var.get().strip(),
                "save_dir": save_dir_var.get().strip(),
                "save_file_name": file_name_var.get().strip()}

    def ui(fn, *a):
        root.after(0, lambda: fn(*a))

    def log(msg):
        for line in str(msg).splitlines() or [""]:
            logger.info(line)
        ui(lambda: (out.insert("end", msg + "\n"), out.see("end")))

    def busy(on):
        go_btn.configure(state="disabled" if on else "normal")

    def worker(job, settings):
        try:
            code, build, tables, version = job()
            ui(fill_info, build_info(build, tables))
            rows = export(code, build, tables, version, log, settings)
            log("")
            log(format_summary(rows))
            save_path = write_character_save(build, rows, settings, log)
            ui(status.set, "Done - character saved as %s" % os.path.basename(save_path))
            ui(update_save_name)
            ui(messagebox.showinfo, "Character saved",
               "The character was saved successfully.\n\nFile name: %s\nFolder: %s"
               % (os.path.basename(save_path), os.path.dirname(save_path)))
        except SaveError as e:
            logger.warning("Save not written", exc_info=True)
            log("\nSAVE NOT WRITTEN: %s" % e)
            ui(status.set, "Save not written - see Details / log.")
            ui(log_section.toggle, True)
            ui(messagebox.showerror, "Save not written", "The character save was not written:\n\n%s" % e)
        except Exception as e:  # noqa
            logger.exception("Download failed")
            log("\nERROR: %s" % e)
            log("(Full details are in %s)" % LOG_FILE)
            if isinstance(e, FetchError):
                log("\nThe site blocked the download. Install curl_cffi and try again:\n"
                    "    pip install curl_cffi")
            ui(status.set, "Failed - see Details / log.")
            ui(log_section.toggle, True)
        finally:
            ui(busy, False)

    def pick_from_list(title, prompt, labels, default):
        """Popup with a scrollable list (Maxroll gear sets, profile days and events).
        Returns the chosen index or None."""
        win = tk.Toplevel(root)
        win.title(title)
        win.transient(root)
        box = ttk.Frame(win, padding=14)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=prompt).pack(anchor="w", pady=(0, 8))
        lst_frame = ttk.Frame(box)
        lst_frame.pack(fill="both", expand=True)
        lst = tk.Listbox(lst_frame, height=min(15, max(5, len(labels))), width=40,
                         exportselection=False, activestyle="dotbox")
        sb = ttk.Scrollbar(lst_frame, orient="vertical", command=lst.yview)
        lst.configure(yscrollcommand=sb.set)
        lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for label in labels:
            lst.insert("end", label)
        lst.selection_set(default)
        lst.activate(default)
        lst.see(default)
        result = {"index": None}

        def ok(*_):
            sel = lst.curselection()
            if sel:
                result["index"] = sel[0]
                win.destroy()
        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Download", command=ok).pack(side="right", padx=(0, 8))
        lst.bind("<Double-Button-1>", ok)
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        lst.focus_set()
        root.wait_window(win)
        return result["index"]

    def pick_set_dialog(names, default):
        return pick_from_list("Choose a gear set", "This planner has %d gear sets. Which one "
                              "should be downloaded?" % len(names), names, default)

    def pick_snapshot_dialog(labels, default):
        return pick_from_list("Choose a day or event", "Which day or event should be downloaded?",
                              labels, default)

    def ask_from_thread(dialog):
        """Wraps a popup so the download thread can call it and wait for the answer."""
        def choose(names, default):
            done, result = threading.Event(), {}

            def ask():
                try:
                    result["index"] = dialog(names, default)
                finally:
                    done.set()
            ui(ask)
            done.wait()
            return result.get("index")
        return choose

    def start(job):
        out.delete("1.0", "end")
        fill_info({"class": "", "level": "", "specialized": [""] * 5, "hotbar": [""] * 5})
        busy(True)
        status.set("Working...")
        threading.Thread(target=worker, args=(job, save_settings()), daemon=True).start()

    def on_go(*_):
        link = link_var.get()
        if not link.strip():
            messagebox.showinfo("Last Epoch Build Downloader - Season 5", "Paste a planner or profile character link first.")
            return
        if not name_var.get().strip():
            messagebox.showinfo("Last Epoch Build Downloader - Season 5", "Enter a character name first.")
            return
        if maxroll.is_maxroll_link(link):
            start(lambda: maxroll.run_from_link(link, log, ask_from_thread(pick_set_dialog)))
        elif le_profile.is_profile_link(link):
            start(lambda: le_profile.run_from_link(link, log, ask_from_thread(pick_snapshot_dialog)))
        else:
            start(lambda: run_from_link(link, log))

    go_btn.configure(command=on_go)
    browse_btn.configure(command=on_browse)
    refresh_btn.configure(command=update_save_name)
    manage_btn.configure(command=open_delete_window)
    entry.bind("<Return>", on_go)
    save_dir_entry.bind("<Return>", update_save_name)   # typed or pasted folder path
    save_dir_entry.bind("<FocusOut>", update_save_name)
    update_save_name()
    entry.focus_set()
    try:  # pre-fill from clipboard if it holds a planner link
        clip = root.clipboard_get()
        if any(k in clip for k in ("lastepochtools.com/planner/", "lastepochtools.com/profile/",
                                   "maxroll.gg/last-epoch/planner/")):
            link_var.set(clip.strip())
    except Exception:  # noqa
        pass
    fit_window()
    root.mainloop()
