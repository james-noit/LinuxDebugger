from textual.widgets import Static


class PanelTabs(Static):
    """Shows the available command panels and how to switch between them."""

    DEFAULT_CSS = """
    PanelTabs {
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def show(self, panel_names: list[str], active_index: int) -> None:
        tags = []
        for index, name in enumerate(panel_names):
            if index == active_index:
                tags.append(f"[reverse bold] {name} [/reverse bold]")
            else:
                tags.append(f"[dim] {name} [/dim]")
        tabs = " ".join(tags)
        self.update(f"ctrl+← {tabs} ctrl+→")
