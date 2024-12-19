import json
import os
import pathlib
import subprocess
import sys
import time
from typing import List, Union

from py3nvml import py3nvml
from PyQt5 import uic  # noqa
from PyQt5.QtCore import (
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
)

# -----------------------------------------------------------
# Globals (I know, I know...)
# -----------------------------------------------------------

VIDEO_TYPES: List[str] = [".mp4", ".mkv", ".webm"]
DEBUGGING = False

# -----------------------------------------------------------
# Utility functions
# -----------------------------------------------------------


def resource_path(relative_path: str) -> str:
    """
    This function constructs the absolute path to a resource file, which can be used to access files bundled with the application.
    It handles the case where the application is running as a standalone executable (not bundled with PyInstaller) and when it's bundled with PyInstaller.

    Parameters:
    relative_path (str): The relative path to the resource file from the application's root directory.

    Returns:
    str: The absolute path to the resource file.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS  # noqa
    except AttributeError:
        # If not running as a bundled executable, use the absolute path of the current directory
        base_path = os.path.abspath("")

    # Join the base path with the relative path to construct the absolute path to the resource file
    return os.path.join(base_path, relative_path)


def has_nvidia_card() -> bool:
    """
    Check if an NVIDIA GPU is available.

    This function initializes the NVML (NVIDIA Management Library) and checks if an NVIDIA GPU is present.
    NVML is a C-based library that provides an interface for managing NVIDIA GPU devices.

    Returns:
    - bool: True if an NVIDIA GPU is detected, False otherwise.

    Raises:
    - Exception: If an error occurs during the initialization of NVML.

    Note:
    - This function uses the `py3nvml` library, which is a Python wrapper for NVML.
    - If NVML is not available or an error occurs during initialization, the function will print an error message and return False.
    """
    try:
        py3nvml.nvmlInit()
        device_count = py3nvml.nvmlDeviceGetCount()
        return device_count > 0
    except Exception as e:
        print(f"Error initializing NVML: {e}")
        return False


def current_time(total_seconds: float, fractional: bool = False) -> str:
    """
    Convert a total number of seconds into a formatted string representing time.

    This function takes a total number of seconds and an optional boolean flag indicating whether to include
    fractional seconds in the output. It calculates the number of hours, minutes, and seconds from the total
    seconds and formats them into a string.

    Parameters:
    total_seconds (float): The total number of seconds to convert.
    fractional (bool, optional): If True, include fractional seconds in the output. Defaults to False.

    Returns:
    str: A formatted string representing the time. If fractional is True, the string includes fractional seconds
         up to three decimal places. Otherwise, it includes only whole seconds.
    """
    hours = int(total_seconds // 3600)
    remainder = total_seconds % 3600
    minutes = int(remainder // 60)
    seconds = remainder % 60  # This is now a float
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02.3f}"
        if fractional
        else f"{hours:02d}:{minutes:02d}:{int(seconds):02d}"
    )


##==========================================================
## Classes
##==========================================================


class WorkerSignals(QObject):
    """
    A class to define signals that can be emitted by worker threads.

    This class inherits from QObject and defines several signals that are used to communicate
    with the main application thread. These signals are emitted when specific events occur,
    such as the completion of analysis or compression tasks, or when the timer ticks.

    Attributes:
    analysisDone: A signal that is emitted when the analysis of a file is done.
                  It carries the filename and the calculated bitrate as parameters.
    compressionDone: A signal that is emitted when the compression of a file is done.
                     It carries the filename as a parameter.
    allFinished: A signal that is emitted when all tasks are completed.
    clockTick: A signal that is emitted once per second to update the elapsed timer.
    """

    # Signals that can be emitted by the workers
    analysisDone = pyqtSignal(str, float)  # filename, bitrate
    compressionDone = pyqtSignal(str)  # filename
    allFinished = pyqtSignal()  # when all tasks are complete
    clockTick = pyqtSignal()  # Signal for elapsed timer updates


class AnalysisRunnable(QRunnable):
    """
    A runnable task for analyzing a video file using ffprobe.

    This class is designed to be executed in a separate thread. It takes a filename and a signals object as parameters.
    The run method executes the ffprobe command to analyze the video file and emits a signal with the analysis result.

    Attributes:
    filename (str): The name of the video file to be analyzed.
    signals (WorkerSignals): The signals object to emit the analysis result.

    Methods:
    run(): Executes the ffprobe command to analyze the video file and emits a signal with the analysis result.
    """

    def __init__(self, filename: str, signals: WorkerSignals):
        """
        Initialize a new instance of AnalysisRunnable.

        This constructor takes a filename and a WorkerSignals object as parameters and initializes the instance variables.

        Parameters:
        filename (str): The name of the video file to be analyzed.
        signals (WorkerSignals): The signals object to emit the analysis result.

        Returns:
        None
        """
        super().__init__()
        self.filename = filename
        self.signals = signals

    def run(self):
        """
        Execute the ffprobe command to analyze the video file and emit a signal with the analysis result.

        This method constructs an ffprobe command to extract the bitrate of the video file. It then executes
        the command using the subprocess module and processes the output to extract the bitrate. If any errors
        occur during the execution or output processing, appropriate error messages are printed.

        Parameters:
        None

        Returns:
        None

        Exceptions:
        subprocess.CalledProcessError: If an error occurs while executing the ffprobe command.
        KeyError: If the output does not contain the expected format or bitrate information.
        Exception: If any other unexpected error occurs.
        """
        # print(f"Analyzing {self.filename}", file=sys.stderr)
        creationflags = (
            subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        )  # No special flags needed for other platforms

        # Set to None as a guard against working with data should ffprobe call fail.
        bitrate: int = None  # noqa
        try:
            command: List[str] = [
                "ffprobe",
                "-v",
                "error",  # Suppress unnecessary output
                "-select_streams",
                "v:0",  # Select the first video stream
                "-show_entries",
                "format=bit_rate",  # Get the bitrate of the video
                "-of",
                "json",  # Output in JSON format
                self.filename,
            ]

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                creationflags=creationflags,
            )
            output: dict = json.loads(result.stdout)
            bitrate = int(output["format"]["bit_rate"])

        except subprocess.CalledProcessError as e:
            print(f"Error executing ffprobe: {e.stderr}")
        except KeyError:
            print("Could not extract bitrate from the output.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

        # Emit the analysis result
        # Must invoke in main thread if needed, but signals are thread-safe for emission
        self.signals.analysisDone.emit(self.filename, bitrate)  # noqa


class CompressionRunnable(QRunnable):
    """
    A class to handle the compression of video files using ffmpeg.

    The class initializes with parameters to configure the compression task.
    It also includes a method to execute the compression task.
    """

    def __init__(
        self,
        filename: str,
        bitrate: int,
        fps: int,
        output_dir: str,
        use_cuda_cores: bool,
        signals: WorkerSignals,
    ):
        """
        Initialize a new instance of CompressionRunnable.

        This constructor takes several parameters to configure the compression task.
        It initializes the instance variables with the provided values.

        Parameters:
        filename (str): The name of the video file to be compressed.
        bitrate (int): The target bitrate for the compressed video.
        fps (int): The target frames per second for the compressed video.
        output_dir (str): The directory where the compressed video will be saved.
        use_cuda_cores (bool): A flag indicating whether to use CUDA cores for hardware acceleration.
        signals (WorkerSignals): The signals object to emit the compression result.

        Returns:
        None
        """
        super().__init__()
        self.filename = filename
        self.bitrate = bitrate
        self.fps = fps
        self.output_dir = output_dir
        self.use_cuda_cores = use_cuda_cores
        self.signals = signals

    def run(self):
        """
        Execute the compression task using ffmpeg.

        Construct an ffmpeg command to compress the video file based on the provided parameters.
        Execute the ffmpeg command using the subprocess module.

        Parameters:
        None

        Returns:
        None

        Exceptions:
        Exception: If an error occurs while executing the ffmpeg command.
        """

        creationflags = (
            subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        )  # No special flags needed for other platforms

        out_file = os.path.join(self.output_dir, os.path.basename(self.filename))

        command: List[Union[str, int]] = [
            "ffmpeg",
            *(["-hwaccel", "cuda"] if self.use_cuda_cores else []),
            "-i",
            self.filename,
            "-vf",
            f"fps={self.fps},scale=-1:-1",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            str(self.bitrate),
            out_file,
        ]

        try:
            subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
        except Exception as e:
            print(f"Error compressing {self.filename}: {e}")

        self.signals.compressionDone.emit(self.filename)  # noqa


class OnScreenTimerThread(QThread):
    """
    A thread that emits a clock tick signal every second to update an on-screen timer.

    Attributes:
    signals (WorkerSignals): The signals object to emit the clock tick signal.

    Methods:
    run(): The main method of the thread. It emits a clock tick signal every second.
    """

    def __init__(self, signals: WorkerSignals) -> None:
        """
        Initialize a new instance of OnScreenTimerThread.

        Parameters:
        signals (WorkerSignals): The signals object to emit the clock tick signal.
        """
        super().__init__()
        self.signals = signals

    def run(self) -> None:
        """
        Emit a clock tick signal every second.

        This method runs in an infinite loop, sleeping for one second between each iteration.
        It emits a clock tick signal using the signals object every second.
        """
        while True:
            time.sleep(1)
            self.signals.clockTick.emit()  # noqa


class VideoCompressionApp(QMainWindow):
    browse_input_button: QPushButton
    browse_output_button: QPushButton
    elapsed_time_label: QLabel
    fps_combo_box: QComboBox
    input_folder_edit: QLineEdit
    output_folder_edit: QLineEdit
    progress_bar: QProgressBar
    quality_edit: QLineEdit
    start_button: QPushButton
    use_cuda_checkbox: QCheckBox

    def __init__(self) -> None:
        """
        Initialize a new instance of VideoCompressionApp.

        This constructor sets up the main window, loads the UI from a file, applies a stylesheet,
        and initializes various UI components. It also checks for the availability of an NVIDIA GPU,
        enables or disables the CUDA checkbox accordingly.

        Parameters:
        None

        Returns:
        None
        """
        super().__init__()

        # Pre-definition of derived attributes, for lint's sake
        self.onscreen_timer_thread = None
        self._start_time = None
        self.completed_files = None
        self.total_files = None
        self.files_to_process = None

        self.setWindowTitle("Video Compression App")
        self.resize(400, 300)

        uic.loadUi(resource_path("VideoCompressionApp.ui"), self)

        with open(resource_path("ElegantDark.qss"), "r") as fh:
            self.setStyleSheet(fh.read())

        if DEBUGGING:
            self.input_folder_edit.setText(r"D:\tempvideos")
            self.output_folder_edit.setText(r"D:\temp25")

        self.browse_input_button.clicked.connect(self.browse_input_folder)
        self.browse_output_button.clicked.connect(self.browse_output_folder)
        self.start_button.clicked.connect(self.start_processing)

        has_card: bool = has_nvidia_card()
        self.use_cuda_checkbox.setEnabled(has_card)
        if has_card:
            self.use_cuda_checkbox.setChecked(True)

        # Create a QThreadPool
        self.threadPool = QThreadPool()
        self.threadPool.setMaxThreadCount(4)  # Optional: limit to 4 threads

        # Create a shared signals object
        self.signals = WorkerSignals()
        self.signals.analysisDone.connect(self.on_analysis_done)  # noqa
        self.signals.compressionDone.connect(self.on_compression_done)  # noqa
        self.signals.clockTick.connect(self.on_clock_tick)  # noqa
        self.signals.allFinished.connect(self.on_all_finished)  # noqa

    def browse_input_folder(self) -> None:
        """
        Open a dialog to select an existing directory for input videos.

        This function uses QFileDialog to open a directory selection dialog.
        The selected directory is then set as the text in the input_folder_edit widget.

        Parameters:
        None

        Returns:
        None

        Note:
        This function is connected to the clicked signal of the browse_input_button.
        """
        folder: str = QFileDialog.getExistingDirectory(
            self, "Select Input Folder", self.input_folder_edit.text()
        )
        if folder != "":
            self.input_folder_edit.setText(str(pathlib.PureWindowsPath(folder)))

    def browse_output_folder(self) -> None:
        """
        Open a dialog to select an existing directory for output videos.

        This function uses QFileDialog to open a directory selection dialog.
        The selected directory is then set as the text in the output_folder_edit widget.

        Parameters:
        None

        Returns:
        None

        Note:
        This function is connected to the clicked signal of the browse_output_button.
        """
        folder: str = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.output_folder_edit.text()
        )
        if folder != "":
            self.output_folder_edit.setText(str(pathlib.PureWindowsPath(folder)))

    def start_processing(self):
        """
        Initiates the video compression process.

        This function disables the start button, retrieves the input and output folder paths,
        creates the list of files to be processed, initializes counters, sets up the progress bar,
        and starts the timer thread for updating the elapsed time. It then submits analysis tasks
        for each file using a thread pool.

        Parameters:
        None

        Returns:
        None
        """
        self.start_button.setEnabled(False)

        input_folder: str = self.input_folder_edit.text()
        output_folder: str = self.output_folder_edit.text()

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        # The actual list of files we're going to be working on
        self.files_to_process: List[str] = [
            os.path.join(input_folder, file)
            for file in os.listdir(input_folder)
            if any(file.endswith(ext) for ext in VIDEO_TYPES)
        ]

        self.total_files: int = len(self.files_to_process)
        self.completed_files = 0
        self.progress_bar.setRange(0, self.total_files)
        self.progress_bar.setValue(0)

        self.statusBar().showMessage("")

        # Create a thread for updating the elapsed time
        self._start_time: float = time.time()  # Start the timer
        self.onscreen_timer_thread = OnScreenTimerThread(self.signals)
        # self.signals.clockTick.connect(self.on_clock_tick)
        self.onscreen_timer_thread.start()

        # First, submit analysis tasks for each file
        for f in self.files_to_process:
            analysis_task = AnalysisRunnable(f, self.signals)
            self.threadPool.start(analysis_task)

    def on_analysis_done(self, filename: str, bitrate: int) -> None:
        """
        This function is called when the analysis of a video file is done.
        It calculates the new bitrate for compression based on the quality setting,
        creates a CompressionRunnable task, and starts it in the thread pool.

        Parameters:
        filename (str): The name of the video file that was analyzed.
        bitrate (int): The bitrate of the video file, calculated during analysis.

        Returns:
        None
        """
        # Analysis done, now start compression
        fps: int = int(self.fps_combo_box.currentText())
        quality: float = float(self.quality_edit.text() or "0.30")
        new_bitrate: int = int(bitrate * quality)
        output_folder = self.output_folder_edit.text()
        use_cuda_cores = self.use_cuda_checkbox.isChecked()

        compression_task = CompressionRunnable(
            filename,
            new_bitrate,
            fps,
            output_folder,
            use_cuda_cores,
            self.signals,
        )
        self.threadPool.start(compression_task)

    def on_compression_done(self, filename) -> None:  # noqa
        """
        This function is called when the compression of a video file is done.
        It increments the counter of completed files, updates the progress bar,
        and shows a message in the status bar. If all files have been compressed,
        it emits a signal to indicate that all tasks are finished.

        Parameters:
        filename (str): The name of the video file that was compressed.

        Returns:
        None
        """
        self.completed_files += 1
        # print(f"Progress: {filename} is {self.completed_files} of {self.total_files}")
        self.progress_bar.setValue(self.completed_files)
        self.statusBar().showMessage(
            f"Completed converting {self.completed_files} of {self.total_files}..."
        )
        if self.completed_files >= self.total_files:
            # All done
            self.signals.allFinished.emit()  # noqa

    def on_clock_tick(self) -> None:
        """
        Updates the elapsed time label with the current elapsed time.

        This function is called every second by the timer thread. It calculates the elapsed time
        by subtracting the start time from the current time. The elapsed time is then formatted
        using the `current_time` function and set as the text of the elapsed time label.

        Parameters:
        None

        Returns:
        None
        """
        self.elapsed_time_label.setText(current_time(time.time() - self._start_time))

    def on_all_finished(self):
        """
        This function is called when all tasks are completed.
        It stops the timer, resets the elapsed time label, and shows a completion message in the status bar.

        Parameters:
        None

        Returns:
        None

        Note:
        - The timer thread is terminated.
        - The start button is enabled.
        - The elapsed time label is reset.
        - A completion message is shown in the status bar.
        """
        end_time: float = time.time()  # Stop the timer
        total_time: float = end_time - self._start_time  # Calculate the total time
        self.onscreen_timer_thread.terminate()  # Stop the timer thread
        self.start_button.setEnabled(True)  # Turn the start button back on
        self.elapsed_time_label.setText("")  # Reset the elapsed time label as well
        self.statusBar().showMessage(
            f"Compression completed in {current_time(total_time, True)}"
        )


if __name__ == "__main__":
    """
    Entry point for the application.

    Starts the QApplication and creates an instance of VideoCompressionApp.
    The application will not terminate until all Qt events have been processed.
     """
    # Set to True for debugging purposes.
    # This will pre-set the input and output folders to specific locations for debugging.
    # DEBUGGING = False
    print(sys.prefix, flush=True, file=sys.stderr)

    # Create a QApplication and run the application
    app: QApplication = QApplication(sys.argv)
    window: VideoCompressionApp = VideoCompressionApp()
    window.show()
    sys.exit(app.exec_())
