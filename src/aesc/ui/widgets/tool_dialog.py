"""Tool Selection Dialog - Quick tool switcher"""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


class ToolSelectionDialog(ModalScreen[str]):
    """Tool selection dialog for quick tool switching.

    Press Ctrl+T to open.
    Press Escape to cancel.
    Select a tool to switch.
    """

    DEFAULT_CSS = """
    ToolSelectionDialog {
        align: center middle;
    }

    #tool-container {
        width: 70;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #tool-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #tool-search {
        margin-bottom: 1;
    }

    #tool-list {
        height: 20;
        border: solid $primary-lighten-1;
    }

    #tool-hint {
        margin-top: 1;
        text-align: center;
        color: $text-muted;
    }

    ListView > ListItem {
        padding: 0 1;
    }

    ListView > ListItem.--highlight {
        background: $accent 30%;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_none", "Cancel"),
        ("ctrl+c", "dismiss_none", "Cancel"),
    ]

    # Security tools available in Kali
    TOOLS = [
        ("nmap", "Network Scanner", "Network discovery and security auditing"),
        ("sqlmap", "SQL Injection Tool", "Automatic SQL injection and database takeover"),
        (
            "gobuster",
            "Directory/DNS Brute-forcer",
            "Directory, file and DNS subdomain brute-forcing",
        ),
        ("nikto", "Web Server Scanner", "Web server vulnerability scanner"),
        ("metasploit", "Exploitation Framework", "Penetration testing framework"),
        (
            "burpsuite",
            "Web Security Testing",
            "Integrated platform for web application security testing",
        ),
        ("hydra", "Login Cracker", "Fast network logon cracker"),
        ("john", "Password Cracker", "John the Ripper password cracker"),
        ("aircrack-ng", "WiFi Security", "WiFi network security auditing toolset"),
        ("wireshark", "Network Analyzer", "Network protocol analyzer"),
        ("hashcat", "Password Recovery", "Advanced password recovery utility"),
        ("dirb", "Web Content Scanner", "Web content scanner"),
        ("wfuzz", "Web Fuzzer", "Web application fuzzer"),
        ("masscan", "Port Scanner", "Fast TCP port scanner"),
        ("enum4linux", "SMB Enumeration", "Tool for enumerating Windows SMB shares"),
    ]

    search_query = reactive("")

    def __init__(self, current_tool: str = "nmap"):
        super().__init__()
        self.current_tool = current_tool
        self.filtered_tools = self.TOOLS.copy()

    def compose(self) -> ComposeResult:
        with Container(id="tool-container"):
            yield Static("Select Security Tool", id="tool-title")
            yield Input(placeholder="Search tools... (type to filter)", id="tool-search")
            yield ListView(*self._create_list_items(), id="tool-list")
            yield Static(
                "[cyan]↑↓[/cyan] Navigate  [green]Enter[/green] Select  [red]Esc[/red] Cancel",
                id="tool-hint",
            )

    def _create_list_items(self) -> list[ListItem]:
        """Create list items for tools."""
        items = []
        for tool_name, tool_title, tool_desc in self.filtered_tools:
            # Highlight current tool
            if tool_name == self.current_tool:
                label_text = Text()
                label_text.append("● ", style="green bold")
                label_text.append(f"{tool_name}", style="cyan bold")
                label_text.append(f" - {tool_title}\n", style="white")
                label_text.append(f"  {tool_desc}", style="dim")
            else:
                label_text = Text()
                label_text.append(f"  {tool_name}", style="cyan")
                label_text.append(f" - {tool_title}\n", style="white")
                label_text.append(f"  {tool_desc}", style="dim")

            items.append(ListItem(Static(label_text)))

        if not items:
            items.append(ListItem(Label("[dim]No tools found[/dim]")))

        return items

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter tools based on search input."""
        self.search_query = event.value.lower()

        # Filter tools
        if self.search_query:
            self.filtered_tools = [
                (name, title, desc)
                for name, title, desc in self.TOOLS
                if (
                    self.search_query in name.lower()
                    or self.search_query in title.lower()
                    or self.search_query in desc.lower()
                )
            ]
        else:
            self.filtered_tools = self.TOOLS.copy()

        # Update list
        tool_list = self.query_one("#tool-list", ListView)
        tool_list.clear()
        for item in self._create_list_items():
            tool_list.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle tool selection."""
        # Get selected tool
        if not self.filtered_tools:
            return

        selected_index = event.list_view.index
        if selected_index is not None and selected_index < len(self.filtered_tools):
            tool_name = self.filtered_tools[selected_index][0]
            self.dismiss(tool_name)

    def action_dismiss_none(self) -> None:
        """Dismiss without selection."""
        self.dismiss(None)
