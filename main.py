import numpy as np
import soundfile as sf
import pyloudnorm as pyln
import sounddevice as sd
import tkinter.filedialog
import tkinter as tk
from pathlib import Path
from ttkthemes import ThemedTk


"""
what's left to do:
- select ouputs
- have spacebar work
- less ugli?
"""


class File:
    def __init__(self, path):
        self.path = path
        data, rate = sf.read(path, dtype="float32")
        self.data = data
        self.mixing_lufs = 1
        self.sample_rate = rate
        self.lufs = self.get_lufs()
        self.string = self.get_string()
        self.length_secs = len(self.data) / self.sample_rate
        self.mastering_data = self.normalize_data(-14) if self.lufs > -14 else self.data

    def get_lufs(self):
        meter = pyln.Meter(self.sample_rate)
        return meter.integrated_loudness(self.data)

    def normalize_data(self, new_loudness):
        return pyln.normalize.loudness(self.data, self.lufs, new_loudness)

    def play(self, lufs_var, quietest, start_time, device=None):
        match lufs_var.get():
            case "raw":
                self.currently_playing = self.data
            case "mixing":
                if quietest != self.mixing_lufs:
                    self.mixing_data = self.normalize_data(quietest)
                    self.mixing_lufs = quietest
                self.currently_playing = self.mixing_data
            case "mastering":
                self.currently_playing = self.mastering_data
        to_play = self.currently_playing[int(start_time * self.sample_rate) :, :]
        to_play = self.fade_in(to_play)
        sd.play(to_play, self.sample_rate, device=device)

    def fade_in(self, data):
        fade_len = 20
        fade = np.expand_dims(np.linspace(0, 1, fade_len), axis=1)
        data[:fade_len, :] *= fade
        return data

    def stop_play(self):
        sd.stop()

    def get_string(self):
        name = Path(self.path).stem
        lufs = "{:.1f}".format(self.lufs)
        return f"{lufs}   {name}"


class Player:
    def __init__(self):
        self.current_track = -1
        self.duration = Duration()
        self.files = []
        self.play_state = "stopped"

        self.root = ThemedTk(theme="scidpink")
        print(self.root.get_themes())
        self.root.title("true audition")
        self.root.geometry("920x600+290+85")

        top_pane = tk.Frame(self.root)
        tk.Button(top_pane, text="load files", command=self.load_files).pack(
            side="left"
        )
        self.lufs_var = tk.StringVar()
        radio_values = {
            "raw": "raw",
            "mixing": "mixing",
            "mastering (-14 lufs, no boosting)": "mastering",
        }
        for text, value in radio_values.items():
            tk.Radiobutton(
                top_pane, text=text, variable=self.lufs_var, value=value
            ).pack(side="right")
        self.lufs_var.trace_add("write", callback=lambda var, index, mode: self.play())
        self.lufs_var.set("raw")

        mid_pane = tk.Frame(self.root)
        self.table_strings_var = tk.StringVar(value=[])
        lbox = tk.Listbox(mid_pane, listvariable=self.table_strings_var)
        lbox.pack(fill="both")
        lbox.bind("<<ListboxSelect>>", lambda e: self.track_select(lbox.curselection()))

        self.waveform = tk.Canvas(mid_pane)
        self.waveform.pack(fill="both")
        self.waveform.bind("<Button-1>", lambda event: self.seek(event.x))

        bottom_pane = tk.Frame(self.root)
        tk.Button(bottom_pane, text="play", command=self.play).pack(side="left")
        tk.Button(bottom_pane, text="pause", command=self.pause).pack(side="left")
        tk.Button(bottom_pane, text="stop", command=self.stop).pack(side="left")

        top_pane.pack(fill="x")
        mid_pane.pack(fill="both")
        bottom_pane.pack(fill="x")

        self.root.bind("<space>", lambda event: self.space_bar(event))

        self.update_play()

    def space_bar(self, event):
        print(self.play_state)
        print(event)
        if self.play_state == "stopped" or self.play_state == "paused":
            self.play()
        else:
            self.pause()

    def run(self):
        self.root.mainloop()

    def load_files(self):
        file_paths = tkinter.filedialog.askopenfilenames()
        for file_path in file_paths:
            try:
                self.files.append(File(file_path))
            except sf.LibsndfileError:
                pass
        self.update_table()
        if self.play_state == "playing":
            self.play()

    def play(self):
        if not self.files:
            return
        if self.current_track == -1:
            self.track_select((0,))
        else:
            quietest = np.min([file.lufs for file in self.files])
            self.current_track.play(
                self.lufs_var, quietest, start_time=self.duration.duration
            )
            self.duration.start(sd.get_stream().time)
            self.get_waveform()
            self.play_state = "playing"

    def pause(self):
        if self.play_state == "paused":
            return
        self.current_track.stop_play()
        self.play_state = "paused"

    def stop(self):
        if self.play_state == "stopped":
            return
        self.duration.reset()
        self.current_track.stop_play()
        self.draw_waveform()
        self.play_state = "stopped"

    def update_table(self):
        names = [file.string for file in self.files]
        self.table_strings_var.set(names)

    def track_select(self, selection):
        self.current_track = self.files[selection[0]]
        self.play()

    def get_waveform(self):
        width = self.waveform.winfo_width()
        height = self.waveform.winfo_height()
        data = self.current_track.currently_playing
        maxes = np.amax(data, axis=1)
        self.bars = []
        for clump in np.array_split(maxes, width):
            self.bars.append(clump.max() * height)

    def draw_waveform(self):
        self.waveform.delete("all")
        height = self.waveform.winfo_height()
        ratio_played = self.duration.duration / self.current_track.length_secs
        cutoff = int(len(self.bars) * ratio_played)
        for i, bar in enumerate(self.bars):
            color = "grey" if i < cutoff else "black"
            self.waveform.create_line(i, height, i, height - bar, fill=color, width=1)

    def seek(self, loc):
        time = self.current_track.length_secs * (loc / self.waveform.winfo_width())
        self.duration.reset(time)
        self.play()

    def update_play(self):
        try:
            if self.play_state == "playing":
                self.duration.update(sd.get_stream().time)
                self.draw_waveform()
        except RuntimeError:
            pass
        except sd.PortAudioError:
            pass
        self.root.after(100, self.update_play)


class Duration:
    def __init__(self):
        self.last_call = 0
        self.duration = 0

    def update(self, current_time):
        self.duration += current_time - self.last_call
        self.last_call = current_time

    def reset(self, time=0):
        self.duration = time

    def start(self, starting_time):
        self.last_call = starting_time


if __name__ == "__main__":
    test = Player()
    test.run()
