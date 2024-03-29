import numpy as np
import soundfile as sf
import pyloudnorm as pyln
import sounddevice as sd
import tkinter.filedialog
import tkinter as tk
from pathlib import Path
from ttkthemes import ThemedTk
import ttkthemes


class GUI:
    def __init__(self):
        self.player = Player()

        self.root = ThemedTk(theme="scidpink")
        self.root.title("true audition")
        self.root.geometry("920x520+290+85")
        self.padx = (3, 0)
        self.pady = (3, 0)

        top_pane = tk.Frame(self.root)
        tk.Button(top_pane, text="load files", command=self.load_files).pack(
            side="left"
        )
        self.output_device_var = tkinter.StringVar(self.root)
        # self.output_devices_var = tkinter.StringVar(self.root)
        self.output_device_var.set(self.player.device)
        output_devices = [
            device["name"]
            for device in sd.query_devices()
            if device["max_output_channels"] > 0
        ]
        self.output_device_menu = tkinter.OptionMenu(
            top_pane, self.output_device_var, *output_devices
        )
        self.output_device_menu.pack(side="left")
        self.output_device_var.trace_add(
            "write", callback=lambda var, index, mode: self.output_device_changed()
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
        self.status = tk.Text(top_pane, height=1, background="light blue")
        self.status.pack(side="left")

        mid_pane = tk.Frame(self.root)
        self.table_strings_var = tk.StringVar(value=[])
        self.lbox = tk.Listbox(
            mid_pane,
            listvariable=self.table_strings_var,
            background="light blue",
        )
        self.lbox.pack(fill="both")
        self.lbox.bind(
            "<<ListboxSelect>>",
            lambda e: self.track_select(self.lbox.curselection()),
        )

        self.waveform = tk.Canvas(mid_pane, background="light blue")
        self.waveform.pack(fill="both")
        self.waveform.bind("<Button-1>", lambda event: self.seek(event.x))

        bottom_pane = tk.Frame(self.root)
        tk.Button(bottom_pane, text="play", command=self.player.play).pack(side="left")
        tk.Button(bottom_pane, text="pause", command=self.player.pause).pack(
            side="left"
        )
        tk.Button(bottom_pane, text="stop", command=self.stop).pack(side="left")

        tk.Button(
            bottom_pane,
            text="remove track",
            command=lambda: self.remove_track(self.lbox.curselection()),
        ).pack(side="right")
        top_pane.pack(fill="x")
        mid_pane.pack(fill="both")
        bottom_pane.pack(fill="x")

        self.root.bind("<Key>", lambda e: self.key_press(e))

        self.playhead = 0
        self.waveform_width = self.waveform.winfo_width()
        self.update_waveform_playhead()
        self.update_waveform_resize()

        self.loading = False

        self.listened_color = "grey"
        self.unlistened_color = "white"

        self.playing_animation = AsciiAnimamtion("☆*。★ﾟ*♪ヾ(☆ゝз・)ノ    ", 100)
        self.loading_animaiton = AsciiAnimamtion("loading    (＠_＠)    ", 100)
        self.sitting_animation = AsciiAnimamtion("(◕‿◕)    ", 100)
        self.clipping_animation = AsciiAnimamtion("probably clips    (ﾒ` ﾛ ´)    ", 100)
        self.update_animations()

        self.clipping_text = None

        self.do_padding(self.root)

    def output_device_changed(self):
        self.player.set_output_device(self.output_device_var.get())

    def do_padding(self, obj):
        for child in obj.winfo_children():
            self.do_padding(child)
        if type(obj) != tk.Frame:
            try:
                obj.pack_configure(padx=self.padx, pady=self.pady)
            except:
                pass

    def key_press(self, event):
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def set_lufs_status(self):
        self.player.set_lufs_mode(self.lufs_var.get())
        if self.player.tracks:
            self.new_waveform()

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
        self.loading = True
        self.player.add_files(tkinter.filedialog.askopenfilenames())
        self.new_waveform()
        self.update_table()
        self.loading = False

    def update_table(self):
        names = self.player.get_strings()
        self.table_strings_var.set(names)

    def remove_track(self, selection):
        if len(self.player.tracks) == 0:
            return
        if not selection:
            return
        selection = selection[0]
        if len(self.player.tracks) == 1:
            self.player.remove(selection)
            self.waveform.delete("all")
            self.update_table()
        else:
            self.player.remove(selection)
            new_track = (
                selection - 1 if selection == len(self.player.tracks) else selection
            )
            self.track_select([new_track])
            self.update_table()
            self.lbox.selection_clear(0, "end")
            self.lbox.selection_set(new_track)

    def track_select(self, selection):
        if not selection:
            return
        selection = selection[0]
        code = self.player.set_current_track(selection)
        if code == "no tracks":
            return
        elif code != "no_change":
            self.new_waveform()
        self.player.play()

    def new_waveform(self):
        if self.player.tracks:
            self.get_waveform()
            self.playhead = 0
            self.draw_waveform()

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
        for i, bar in enumerate(self.bars):
            self.waveform.create_line(
                i, height, i, height - bar, fill=self.unlistened_color, width=1
            )

    def seek(self, loc):
        self.player.seek_to_ratio(loc / self.waveform.winfo_width())
        if self.player.has_active_track():
            self.update_waveform()
            self.player.play()

    def update_waveform(self):
        player_playhead = int(self.player.ratio_played() * len(self.bars))
        diff = player_playhead - self.playhead
        if diff != 0:
            offsets = list(range(0, diff, 1 if diff >= 0 else -1))
            locs = [offset + self.playhead for offset in offsets]
            locs = np.clip(locs, a_min=None, a_max=len(self.bars) - 1)
            colors = [
                self.listened_color if diff >= 0 else self.unlistened_color
                for _ in locs
            ]
            height = self.waveform.winfo_height()
            for loc, color in zip(locs, colors):
                self.waveform.create_line(
                    loc, height, loc, height - self.bars[loc], fill=color, width=1
                )
            self.playhead = player_playhead

    def update_waveform_playhead(self):
        if self.player.is_playing():
            self.update_waveform()
        self.root.after(10, self.update_waveform_playhead)

    def update_waveform_resize(self):
        if (
            self.player.current_track != None
            and self.waveform_width != self.waveform.winfo_width()
        ):
            self.new_waveform()
            self.waveform_width = self.waveform.winfo_width()
        self.root.after(200, self.update_waveform_resize)

    def update_animations(self):
        # playing anim
        if self.player.is_playing():
            names = self.player.get_strings()
            current_name = self.player.current_track.string
            for i, name in enumerate(names):
                if name == current_name:
                    names[i] += "  |  " + self.playing_animation.step()
            self.table_strings_var.set(names)
        # status anim
        self.status.delete(1.0, "end")
        if self.loading:
            self.status.insert(1.0, self.loading_animaiton.step())
        else:
            self.status.insert(1.0, self.sitting_animation.step())
        # clipping anim
        if self.player.clipping:
            if self.clipping_text:
                self.waveform.delete(self.clipping_text)
            self.clipping_text = self.waveform.create_text(
                0, 0, text=self.clipping_animation.step(), anchor="nw"
            )

        self.root.after(500, self.update_animations)


class AsciiAnimamtion:
    def __init__(self, seed, repeats, direction="right"):
        self.frame = seed
        self.repeats = repeats
        if direction == "left":
            self.anim_func = self.backward_turn
        else:
            self.anim_func = self.forward_turn

    def step(self):
        frame = self.frame * self.repeats
        self.frame = self.anim_func(self.frame)
        return frame

    def forward_turn(self, frame):
        return frame[-1] + frame[:-1]

    def backward_turn(self, frame):
        return frame[1:] + frame[0]


class Player:
    def __init__(self):
        self.current_track = None
        self.tracks = []
        self.playhead = 0
        self.current_sample = 0
        self.sample_rate = 0
        self.stream = sd.OutputStream()
        self.lufs_mode = "raw"
        self.clipping = False
        self.device = sd.query_devices()[sd.default.device[1]]["name"]

    def has_active_track(self):
        return self.current_track != None

    def get_output_devices(self):
        return [
            device["name"]
            for device in sd.query_devices()
            if device["max_output_channels"] > 0
        ]

    def get_device_number(self):
        for device in sd.query_devices():
            if device["name"] == self.device:
                return device["index"]
        Warning("Device not found, using default")
        return [sd.default.device[1]]

    def set_output_device(self, device):
        was_playing = self.is_playing()
        if device == self.device:
            return
        self.device = device
        self.new_stream()
        if was_playing:
            self.play()

    def is_playing(self):
        return self.stream.active

    def ratio_played(self):
        if self.current_track == None:
            return 0
        if self.current_track.length_secs == 0:
            return 0
        return self.playhead / self.current_track.length_secs

    def remove(self, track_num):
        if self.current_track == None:
            return
        del self.tracks[track_num]
        if not self.tracks:
            self.current_track = None
            self.stream.close()
            self.sample_rate = 0
        else:
            self.get_mixing_lufs()
        self.check_clipped()

    def load_samples(self, outdata, frames, time, status):
        data = self.current_track.get_data(
            self.current_sample,
            self.current_sample + frames,
            self.lufs_mode,
        )
        if len(data) == 0:  # song finished
            self.stop()
            return
        elif len(data) < len(outdata):  # remainder < buffer
            outdata[:] = np.zeros_like(outdata)
            outdata[: len(data)] = data
        else:  # plently left
            outdata[:] = data
        self.current_sample += frames
        self.playhead = self.current_sample / self.sample_rate

    def set_lufs_mode(self, mode):
        self.lufs_mode = mode
        if self.tracks:
            self.check_clipped()

    def get_currently_playing_data(self):
        return self.current_track.get_data(0, -1, self.lufs_mode)

    def seek_to_ratio(self, ratio):
        if self.current_track == None:
            return
        self.playhead = self.current_track.length_secs * ratio
        self.current_sample = int(len(self.current_track.data) * ratio)

    def add_files(self, new_files_paths):
        for path in new_files_paths:
            try:
                self.tracks.append(Song(path))
            except sf.LibsndfileError:
                pass
        if self.tracks:
            self.get_mixing_lufs()
        if self.current_track == None and self.tracks:  # first start
            self.set_current_track(0)
            return "first start"

    def get_mixing_lufs(self):
        mixing_lufs = np.min([song.lufs for song in self.tracks])
        for track in self.tracks:
            track.make_mixing_data(mixing_lufs)
        while self.check_mix_clipped():
            for track in self.tracks:
                track.make_mixing_data(mixing_lufs)
            mixing_lufs -= 1

    def check_mix_clipped(self):
        return any([track.check_clipped("mixing") for track in self.tracks])

    def check_clipped(self):
        if self.current_track:
            self.clipping = self.current_track.check_clipped(self.lufs_mode)
        else:
            self.clipping = False

    def set_current_track(self, track_num):
        if self.current_track == self.tracks[track_num]:
            return "no change"
        elif not self.tracks:
            return "no tracks"
        self.current_track = self.tracks[track_num]
        self.check_clipped()
        if self.current_track.sample_rate != self.sample_rate:
            self.sample_rate = self.current_track.sample_rate
            self.new_stream()
            self.current_sample = int(self.playhead * self.sample_rate)

    def new_stream(self):
        self.stream.close()
        self.stream = sd.OutputStream(
            device=self.get_device_number(),
            samplerate=self.sample_rate,
            callback=self.load_samples,
        )

    def get_strings(self):
        return [track.string for track in self.tracks]

    def play(self):
        if self.current_track == None:
            return
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
        self.sample_rate = rate
        self.lufs = self.get_lufs()
        self.string = self.get_string()
        self.length_secs = len(self.data) / self.sample_rate
        self.mastering_data = self.normalize_data(-14) if self.lufs > -14 else self.data
        self.mixing_data = data

    def get_lufs(self):
        meter = pyln.Meter(self.sample_rate)
        return meter.integrated_loudness(self.data)

    def normalize_data(self, new_loudness):
        return pyln.normalize.loudness(self.data, self.lufs, new_loudness)

    def get_string(self):
        name = Path(self.path).stem
        lufs = "{:.1f}".format(self.lufs)
        str = f"{lufs}  |  {name}"
        if self.check_clipped("raw"):
            str = f"{str}  |  clipping! (is it an mp3?)"
        return str

    def make_mixing_data(self, lufs):
        self.mixing_data = self.normalize_data(lufs)

    def check_clipped(self, lufs_mode):
        return np.max(np.abs(self.get_data_for_mode(lufs_mode))) >= 1.0

    def get_data(self, start, end, lufs_mode):
        return self.get_data_for_mode(lufs_mode)[start:end, :]

    def get_data_for_mode(self, lufs_mode):
        match lufs_mode:
            case "raw":
                return self.data
            case "mixing":
                return self.mixing_data
            case "mastering":
                return self.mastering_data

    def fade_in(self, data):
        fade_len = 20
        fade = np.expand_dims(np.linspace(0, 1, fade_len), axis=1)
        data[:fade_len, :] *= fade
        return data


if __name__ == "__main__":
    test = GUI()
    test.run()
