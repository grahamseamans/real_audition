import numpy as np
import soundfile as sf
import pyloudnorm as pyln
import sounddevice as sd
import tkinter.filedialog
import tkinter as tk
from pathlib import Path
from ttkthemes import ThemedTk


class GUI:
    def __init__(self):
        self.player = Player()

        self.root = ThemedTk(theme="scidpink")
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
        self.lufs_var.trace_add(
            "write", callback=lambda var, index, mode: self.set_lufs_status()
        )
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
        tk.Button(bottom_pane, text="play", command=self.player.play).pack(side="left")
        tk.Button(bottom_pane, text="pause", command=self.player.pause).pack(
            side="left"
        )
        tk.Button(bottom_pane, text="stop", command=self.stop).pack(side="left")

        top_pane.pack(fill="x")
        mid_pane.pack(fill="both")
        bottom_pane.pack(fill="x")

        self.root.bind("<Key>", lambda e: self.key_press(e))

        self.update_play()

    def key_press(self, event):
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def set_lufs_status(self):
        self.player.set_lufs_mode(self.lufs_var.get())
        self.get_waveform()

    def space_bar(self, event):
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.player.stop()
        self.draw_waveform()

    def run(self):
        self.root.mainloop()

    def load_files(self):
        self.player.add_files(tkinter.filedialog.askopenfilenames())
        self.update_table()

    def update_table(self):
        names = self.player.get_strings()
        self.table_strings_var.set(names)

    def track_select(self, selection):
        self.player.set_current_track(selection[0])
        self.player.play()
        self.get_waveform()

    def get_waveform(self):
        width = self.waveform.winfo_width()
        height = self.waveform.winfo_height()
        data = self.player.get_currently_playing_data()
        maxes = np.amax(data, axis=1)
        self.bars = []
        for clump in np.array_split(maxes, width):
            self.bars.append(clump.max() * height)

    def draw_waveform(self):
        self.waveform.delete("all")
        height = self.waveform.winfo_height()
        ratio_played = self.player.ratio_played()
        cutoff = int(len(self.bars) * ratio_played)
        for i, bar in enumerate(self.bars):
            color = "grey" if i < cutoff else "black"
            self.waveform.create_line(i, height, i, height - bar, fill=color, width=1)

    def seek(self, loc):
        self.player.seeked_to_ratio(loc / self.waveform.winfo_width())

    def update_play(self):
        try:
            if self.player.is_playing():
                self.draw_waveform()
        except RuntimeError:
            pass
        except sd.PortAudioError:
            pass
        self.root.after(10, self.update_play)


class Player:
    def __init__(self):
        self.current_track = -1
        self.songs = []
        self.playhead = 0
        self.current_sample = 0
        self.sample_rate = 0
        self.quietest = -14
        self.stream = sd.OutputStream()
        self.lufs_mode = "raw"

    def is_playing(self):
        return self.stream.active

    def ratio_played(self):
        if self.current_track.length_secs == 0:
            return 0
        return self.playhead / self.current_track.length_secs

    def load_samples(self, outdata, frames, time, status):
        outdata[:] = self.current_track.get_data(
            self.current_sample,
            self.current_sample + frames,
            self.lufs_mode,
            self.quietest,
        )
        self.current_sample += frames
        self.playhead = self.current_sample / self.sample_rate

    def set_lufs_mode(self, mode):
        self.plufs_mode = mode

    def get_currently_playing_data(self):
        return self.current_track.get_data(0, -1, self.lufs_mode, self.quietest)

    def add_files(self, new_files_paths):
        for path in new_files_paths:
            try:
                self.songs.append(Song(path))
            except sf.LibsndfileError:
                pass
        self.quietest = np.min([song.lufs for song in self.songs])

    def set_current_track(self, track_num):
        if not self.songs:
            return
        self.current_track = self.songs[track_num]
        if self.current_track.sample_rate != self.sample_rate:
            self.sample_rate = self.current_track.sample_rate
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate, callback=self.load_samples
            )
            self.current_sample = self.playhead * self.sample_rate

    def get_strings(self):
        return [song.string for song in self.songs]

    def play(self):
        if not self.songs:
            return
        if self.current_track == -1:
            self.current_track = 0
        else:
            self.stream.start()

    def pause(self):
        self.stream.stop()

    def stop(self):
        self.stream.stop()
        self.playhead = 0
        self.current_sample = 0


class Song:
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

    def get_string(self):
        name = Path(self.path).stem
        lufs = "{:.1f}".format(self.lufs)
        return f"{lufs}   {name}"

    def get_data(self, start, end, lufs_mode, quietest):
        match lufs_mode:
            case "raw":
                self.currently_playing = self.data
            case "mixing":
                if quietest != self.mixing_lufs:
                    self.mixing_data = self.normalize_data(quietest)
                    self.mixing_lufs = quietest
                self.currently_playing = self.mixing_data
            case "mastering":
                self.currently_playing = self.mastering_data
        to_play = self.currently_playing[start:end, :]
        return to_play
        # to_play = self.fade_in(to_play)
        # sd.play(to_play, self.sample_rate, device=device)

    # def fade_in(self, data):
    #     fade_len = 20
    #     fade = np.expand_dims(np.linspace(0, 1, fade_len), axis=1)
    #     data[:fade_len, :] *= fade
    #     return data

    # def stop_play(self):
    #     sd.stop()


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
    test = GUI()
    test.run()
