import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import yaml
import re


def edit_config(config_file_path):
    with open(config_file_path, 'r') as file:
        config_str = file.read()
        config = yaml.safe_load(config_str)

    root = tk.Tk()
    root.title("Edit Configuration")
    root.geometry("800x600")

    main_frame = ttk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True)

    notebook = ttk.Notebook(main_frame)
    notebook.pack(fill=tk.BOTH, expand=True)

    def create_tab(name, config_section):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=name)

        canvas = tk.Canvas(tab)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        return scrollable_frame, config_section

    def update_config(section, key, value):
        keys = key.split('.')
        d = section
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def create_input(parent, section, key, value, row):
        ttk.Label(parent, text=key).grid(
            row=row, column=0, sticky="w", padx=5, pady=2)
        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            ttk.Checkbutton(parent, variable=var, command=lambda: update_config(
                section, key, var.get())).grid(row=row, column=1, sticky="w", padx=5, pady=2)
        elif isinstance(value, int):
            var = tk.StringVar(value=str(value))
            ttk.Entry(parent, textvariable=var).grid(
                row=row, column=1, sticky="we", padx=5, pady=2)
            var.trace("w", lambda *args: update_config(section, key,
                      int(var.get()) if var.get().isdigit() else 0))
        elif isinstance(value, list):
            text = tk.Text(parent, height=3, width=40)
            text.grid(row=row, column=1, sticky="we", padx=5, pady=2)
            text.insert(tk.END, '\n'.join(map(str, value)))
            text.bind("<FocusOut>", lambda e: update_config(
                section, key, text.get("1.0", tk.END).strip().split('\n')))
        else:
            var = tk.StringVar(value=str(value))
            ttk.Entry(parent, textvariable=var).grid(
                row=row, column=1, sticky="we", padx=5, pady=2)
            var.trace("w", lambda *args: update_config(section, key, var.get()))

    def create_inputs(parent, config_dict, section, prefix=''):
        row = 0
        for key, value in config_dict.items():
            full_key = f"{prefix}{key}" if prefix else key
            if isinstance(value, dict):
                ttk.Label(parent, text=key, font=("", 10, "bold")).grid(
                    row=row, column=0, sticky="w", padx=5, pady=5)
                row += 1
                row = create_inputs(parent, value, section, f"{full_key}.")
            else:
                create_input(parent, section, full_key, value, row)
                row += 1
        return row

    def create_sync_jobs_tab(parent, sync_jobs):
        row = 0
        for job_name, job_config in sync_jobs.items():
            ttk.Label(parent, text=job_name, font=("", 12, "bold")).grid(
                row=row, column=0, sticky="w", padx=5, pady=10)
            row += 1
            for key, value in job_config.items():
                create_input(parent, sync_jobs, f"{
                             job_name}.{key}", value, row)
                row += 1
            ttk.Separator(parent, orient='horizontal').grid(
                row=row, column=0, columnspan=2, sticky="ew", pady=10)
            row += 1

    general_frame, general_config = create_tab("General", config)
    create_inputs(general_frame, {k: v for k, v in config.items() if k != 'sync_jobs' and k !=
                  'rclone_options' and k != 'bisync_options' and k != 'resync_options'}, general_config)

    sync_jobs_frame, sync_jobs_config = create_tab(
        "Sync Jobs", config['sync_jobs'])
    create_sync_jobs_tab(sync_jobs_frame, config['sync_jobs'])

    rclone_options_frame, rclone_options_config = create_tab(
        "Rclone Options", config['rclone_options'])
    create_inputs(rclone_options_frame,
                  config['rclone_options'], rclone_options_config)

    bisync_options_frame, bisync_options_config = create_tab(
        "Bisync Options", config['bisync_options'])
    create_inputs(bisync_options_frame,
                  config['bisync_options'], bisync_options_config)

    resync_options_frame, resync_options_config = create_tab(
        "Resync Options", config['resync_options'])
    create_inputs(resync_options_frame,
                  config['resync_options'], resync_options_config)

    def save_config():
        # Preserve comments and structure
        with open(config_file_path, 'r') as file:
            lines = file.readlines()

        def update_value(lines, path, value):
            pattern = re.compile(r'^(\s*{}: ).*$'.format(re.escape(path)))
            for i, line in enumerate(lines):
                if pattern.match(line):
                    lines[i] = pattern.sub(r'\1{}\n'.format(value), line)
                    return True
            return False

        def update_config_lines(config_dict, prefix=''):
            for key, value in config_dict.items():
                full_key = f"{prefix}{key}" if prefix else key
                if isinstance(value, dict):
                    update_config_lines(value, f"{full_key}.")
                else:
                    if not update_value(lines, full_key, value):
                        lines.append(f"{full_key}: {value}\n")

        update_config_lines(config)

        with open(config_file_path, 'w') as file:
            file.writelines(lines)

        messagebox.showinfo("Success", "Configuration saved successfully")
        root.destroy()

    ttk.Button(root, text="Save", command=save_config).pack(pady=10)

    root.mainloop()
