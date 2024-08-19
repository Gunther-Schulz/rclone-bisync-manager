import tkinter
from tkinter import ttk, messagebox
import yaml


def edit_config(config_file_path):
    with open(config_file_path, 'r') as file:
        config = yaml.safe_load(file)

    root = tkinter.Tk()
    root.title("Edit Configuration")
    root.geometry("600x400")

    main_frame = ttk.Frame(root)
    main_frame.pack(fill=tkinter.BOTH, expand=True)

    canvas = tkinter.Canvas(main_frame)
    scrollbar = ttk.Scrollbar(
        main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    main_frame.pack(fill=tkinter.BOTH, expand=True)
    canvas.pack(side="left", fill=tkinter.BOTH, expand=True)
    scrollbar.pack(side="right", fill="y")

    def update_config(key, value):
        keys = key.split('.')
        d = config
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def create_input(parent, key, value, row):
        ttk.Label(parent, text=key).grid(
            row=row, column=0, sticky="w", padx=5, pady=2)
        if isinstance(value, bool):
            var = tkinter.BooleanVar(value=value)
            ttk.Checkbutton(parent, variable=var, command=lambda: update_config(
                key, var.get())).grid(row=row, column=1, sticky="w", padx=5, pady=2)
        elif isinstance(value, int):
            var = tkinter.StringVar(value=str(value))
            ttk.Entry(parent, textvariable=var).grid(
                row=row, column=1, sticky="we", padx=5, pady=2)
            var.trace("w", lambda *args: update_config(key,
                      int(var.get()) if var.get().isdigit() else 0))
        else:
            var = tkinter.StringVar(value=str(value))
            ttk.Entry(parent, textvariable=var).grid(
                row=row, column=1, sticky="we", padx=5, pady=2)
            var.trace("w", lambda *args: update_config(key, var.get()))

    def create_inputs(parent, config_dict, prefix=''):
        row = 0
        for key, value in config_dict.items():
            full_key = f"{prefix}{key}" if prefix else key
            if isinstance(value, dict):
                ttk.Label(parent, text=key, font=("", 10, "bold")).grid(
                    row=row, column=0, sticky="w", padx=5, pady=5)
                row += 1
                row = create_inputs(parent, value, f"{full_key}.")
            else:
                create_input(parent, full_key, value, row)
                row += 1
        return row

    create_inputs(scrollable_frame, config)

    def save_config():
        with open(config_file_path, 'w') as file:
            yaml.dump(config, file)
        messagebox.showinfo("Success", "Configuration saved successfully")
        root.destroy()

    ttk.Button(root, text="Save", command=save_config).pack(pady=10)

    root.mainloop()
