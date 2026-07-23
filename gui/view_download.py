from datetime import datetime
from nicegui import ui
from config import BRAND_COLORS, logger


class SpectraDownloadPanel:
    """Issue #46: lets the operator bulk-download recorded spectra files from
    any of the three data/spectra/ subfolders (background, batch, riid), each
    in its own tab with a "select all" checkbox and an extension filter.

    Originally built as a card inside the Spectrum Recording tab, but moved
    into its own top-level "Spectra Download" tab (between Spectrum Recording
    and Hardware & Calibration) since it was making that tab too crowded."""

    # (category key passed to the service, display label for the tab)
    CATEGORIES = [
        ('background', 'Background'),
        ('batch', 'Batch'),
        ('riid', 'RIID'),
    ]

    def __init__(self, service):
        self.service = service
        self.sections = {}
        self.render_layout()

    def render_layout(self):
        with ui.card().classes('w-full p-4 rounded-lg border shadow-md bg-white gap-3').style('border-color: #E2E8F0;'):
            ui.label('Download Recorded Spectra').classes('text-sm font-bold').style(f"color: {BRAND_COLORS['primary']};")

            with ui.tabs().classes('w-full dense border-b').style(f"color: {BRAND_COLORS['secondary']};") as category_selector:
                tab_refs = {key: ui.tab(label, icon='folder').classes('text-xs') for key, label in self.CATEGORIES}

            with ui.tab_panels(category_selector, value=tab_refs['background']).classes('w-full bg-transparent p-0 pt-2'):
                for key, label in self.CATEGORIES:
                    with ui.tab_panel(tab_refs[key]).classes('p-0'):
                        self.sections[key] = _CategoryDownloadSection(self.service, key, label)


class _CategoryDownloadSection:
    """Manages a single category's (background/batch/riid) file picker,
    "select all" checkbox, extension filter, and bulk .zip download. Used by
    SpectraDownloadPanel - one instance per tab."""

    def __init__(self, service, category: str, label: str):
        self.service = service
        self.category = category
        self.label = label
        self.checkboxes = {}  # filename -> ui.checkbox, rebuilt on every refresh
        self.render()

    def render(self):
        with ui.row().classes('w-full gap-2 items-end pt-1'):
            self.ext_filter = ui.select(
                {'ALL': 'All (.json + .spe)', 'JSON': 'JSON only', 'SPE': 'SPE only'},
                value='ALL', label='Filter by Extension'
            ).props('dense outlined').classes('w-52 text-xs')
            ui.button(icon='refresh', on_click=self.refresh_files).props('dense flat round').style(f"color: {BRAND_COLORS['primary']};")

        self.ext_filter.on_value_change(lambda e: self.refresh_files())

        self.select_all_cb = ui.checkbox('Select All', on_change=self.toggle_select_all).classes('text-xs mt-1')

        self.file_list_container = ui.column().classes('w-full gap-1 mt-1') \
            .style('max-height: 220px; overflow-y: auto; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;')

        with ui.row().classes('w-full gap-2 mt-2'):
            self.download_btn = ui.button('Download Selected', icon='download', on_click=self.download_selected)
            self.download_btn.style(f"background-color: {BRAND_COLORS['primary']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('flex-1 text-xs')

            self.delete_btn = ui.button('Delete Selected', icon='delete_forever', on_click=self.confirm_delete_selected)
            self.delete_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('flex-1 text-xs')

        self._build_delete_confirm_dialog()

        self.refresh_files()

    def _build_delete_confirm_dialog(self):
        """Confirmation prompt shown every time Delete Selected is pressed -
        deletion is permanent (no undo/trash), so this is required before
        anything actually gets removed from disk."""
        with ui.dialog() as self.delete_dialog, ui.card().classes('p-4 w-80 space-y-3'):
            ui.label('Confirm Permanent Deletion').classes('text-sm font-bold').style(f"color: {BRAND_COLORS['crimson_trace']};")
            self.delete_confirm_msg = ui.label('').classes('text-xs text-zinc-700')
            with ui.row().classes('w-full gap-2 pt-1'):
                ui.button('Cancel', on_click=self.delete_dialog.close).props('dense outline').classes('flex-1')
                confirm_btn = ui.button('Delete Permanently', icon='delete_forever', on_click=self.execute_delete)
                confirm_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('flex-1')

    def refresh_files(self):
        self.checkboxes = {}
        self.file_list_container.clear()
        files = self.service.list_spectra_files(self.category, self.ext_filter.value)
        self.select_all_cb.set_value(False)
        with self.file_list_container:
            if not files:
                ui.label('No files available.').classes('text-xs text-zinc-400 italic')
            for f in files:
                self.checkboxes[f] = ui.checkbox(f).classes('text-xs')

    def toggle_select_all(self, e):
        for cb in self.checkboxes.values():
            cb.set_value(e.value)

    def download_selected(self):
        selected = [f for f, cb in self.checkboxes.items() if cb.value]
        if not selected:
            ui.notify("Select at least one file to download.", type="negative")
            return

        zip_bytes = self.service.build_spectra_zip(self.category, selected)
        if not zip_bytes:
            ui.notify("Failed to build the download archive - the selected file(s) may no longer exist.", type="negative")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{self.category}_spectra_{timestamp}.zip"
        logger.warning(f"[USER_ACTION] Operator downloaded {len(selected)} spectra file(s) from category '{self.category}': {', '.join(selected)}")
        ui.download(zip_bytes, filename, media_type='application/zip')

    def confirm_delete_selected(self):
        """Opens the confirmation prompt - the actual deletion only happens if
        the operator confirms in execute_delete below."""
        selected = [f for f, cb in self.checkboxes.items() if cb.value]
        if not selected:
            ui.notify("Select at least one file to delete.", type="negative")
            return

        self.delete_confirm_msg.set_text(
            f"Are you sure you want to permanently delete {len(selected)} file(s) "
            f"from {self.label}? This cannot be undone."
        )
        self.delete_dialog.open()

    def execute_delete(self):
        selected = [f for f, cb in self.checkboxes.items() if cb.value]
        ok, msg = self.service.delete_spectra_files(self.category, selected)
        self.delete_dialog.close()
        if ok:
            ui.notify(msg, type="positive")
        else:
            ui.notify(msg, type="negative")
        self.refresh_files()