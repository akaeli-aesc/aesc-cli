"""Results Folder Viewer Dialog - Browse and view session results files"""

from pathlib import Path

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Static

# Default path for backward compatibility
DEFAULT_RESULTS_PATH = Path("/results")


class FileViewer(Static):
    """Widget to display file contents."""

    DEFAULT_CSS = """
    FileViewer {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content: RenderableType = Text("Select a file", style="dim")

    def render(self) -> RenderableType:
        return self._content

    def show_file(self, path: Path) -> None:
        """Display file contents."""
        if not path.exists():
            self._content = Text(f"Not found: {path}", style="red")
            self.refresh(layout=True)
            return

        if not path.is_file():
            self._content = Text("Select a file", style="dim")
            self.refresh(layout=True)
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > 100000:
                content = content[:100000] + "\n\n... [truncated] ..."

            suffix = path.suffix.lower()

            if suffix == ".md":
                self._content = Markdown(content)
            elif suffix in (".json", ".xml", ".yaml", ".yml"):
                lexer = "xml" if suffix == ".xml" else suffix.lstrip(".")
                self._content = Syntax(content, lexer, theme="monokai", line_numbers=True)
            elif suffix in (".py", ".sh", ".bash", ".js", ".ts"):
                lang = {"py": "python", "sh": "bash", "bash": "bash"}.get(
                    suffix.lstrip("."), suffix.lstrip(".")
                )
                self._content = Syntax(content, lang, theme="monokai", line_numbers=True)
            else:
                self._content = Text(content)

            self.refresh(layout=True)

        except Exception as e:
            self._content = Text(f"Error: {e}", style="red")
            self.refresh(layout=True)


class ResultsDialog(ModalScreen):
    """Results folder viewer - VSCode-like file browser.

    Esc to close. Arrow keys to navigate. Enter to select.
    """

    def __init__(self, results_dir: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        self.results_path = results_dir if results_dir is not None else DEFAULT_RESULTS_PATH

    DEFAULT_CSS = """
    ResultsDialog {
        align: center middle;
        background: $background;
    }

    #main {
        width: 100%;
        height: 100%;
        background: $surface;
    }

    #header {
        height: 1;
        width: 100%;
        background: $primary-darken-2;
        padding: 0 1;
    }

    #title {
        color: $text;
    }

    #content {
        width: 100%;
        height: 1fr;
    }

    #sidebar {
        width: 25;
        height: 100%;
        background: $surface-darken-1;
        border-right: solid $primary-darken-1;
    }

    #file-tree {
        width: 100%;
        height: 100%;
    }

    DirectoryTree {
        background: transparent;
    }

    DirectoryTree > .directory-tree--folder {
        text-style: bold;
    }

    DirectoryTree > .directory-tree--file {
        color: $text;
    }

    DirectoryTree:focus > .directory-tree--cursor {
        background: $accent;
        color: $text;
    }

    #viewer-pane {
        width: 1fr;
        height: 100%;
    }

    #path-bar {
        height: 1;
        width: 100%;
        background: $surface-darken-1;
        padding: 0 1;
        color: $text-muted;
    }

    #viewer-scroll {
        width: 100%;
        height: 1fr;
        padding: 0 1;
    }

    #viewer {
        width: 100%;
    }

    #no-results {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }

    #no-results-text {
        text-align: center;
        color: $warning;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="main"):
            with Container(id="header"):
                # Show session folder in title
                title = f"RESULTS: {self.results_path.name}  [Esc to close]"
                yield Static(title, id="title")

            if not self.results_path.exists():
                with Container(id="no-results"):
                    yield Static(
                        f"No results folder: {self.results_path}\n\n"
                        "Mount with: docker run -v ./results:/results ...",
                        id="no-results-text",
                    )
            else:
                with Horizontal(id="content"):
                    with VerticalScroll(id="sidebar"):
                        yield DirectoryTree(str(self.results_path), id="file-tree")

                    with Container(id="viewer-pane"):
                        yield Static("", id="path-bar")
                        with VerticalScroll(id="viewer-scroll"):
                            yield FileViewer(id="viewer")

    def on_mount(self) -> None:
        """Focus the file tree on mount."""
        try:
            tree = self.query_one("#file-tree", DirectoryTree)
            tree.focus()
        except Exception:
            pass

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection."""
        file_path = Path(event.path)

        # Update path bar
        try:
            path_bar = self.query_one("#path-bar", Static)
            rel = (
                file_path.relative_to(self.results_path)
                if file_path.is_relative_to(self.results_path)
                else file_path
            )
            path_bar.update(str(rel))
        except Exception:
            pass

        # Show file
        viewer = self.query_one("#viewer", FileViewer)
        viewer.show_file(file_path)

        # Scroll to top
        try:
            scroll = self.query_one("#viewer-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def action_dismiss(self) -> None:
        """Close dialog."""
        self.dismiss()
