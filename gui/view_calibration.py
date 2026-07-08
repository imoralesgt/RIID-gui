import json
from nicegui import ui
from config import BRAND_COLORS

class HardwareCalibrationPanel:
    def __init__(self, system):
        self.system = system
        self.render_layout()

    def render_layout(self):
        ui.markdown("⚙️ **Non-Volatile Instrument Profiles:** Calibration committed to records.").classes('text-xs text-zinc-600 q-mb-xs')
        with ui.row().classes('w-full gap-3 items-stretch no-wrap'):
            
            # LEFT COLUMN: Non-Volatile Profiles & Energy Coefficients
            with ui.column().classes('gap-3 flex-1').style('width: 50%;'):
                with ui.card().classes('w-full p-4 rounded-lg border shadow-md bg-white space-y-3'):
                    with ui.row().classes('w-full gap-3 items-center'):
                        ui.label(f"Base S/N: {self.system.serial_number}").classes('text-xs font-mono font-bold text-blue-800 bg-blue-50 px-2 py-1 rounded border')
                        ui.input('System ID', value=self.system.hw_profile.get('SYS-ID', 'SYS-STANDBY'), 
                                 on_change=lambda e: self.system.hw_profile.update({'SYS-ID': e.value})).props('dense outlined').classes('w-28 text-xs')
                        ui.input('Analyzer Model Name', value=self.system.hw_profile.get('Analyzer name', 'UNKNOWN'), on_change=lambda e: self.system.hw_profile.update({'Analyzer name': e.value})).props('dense outlined').classes('flex-1 text-xs')
                    with ui.row().classes('w-full gap-3'):
                        ui.input('Detector Type Class', value=self.system.hw_profile.get('Detector type', 'NaI(Tl)'), on_change=lambda e: self.system.hw_profile.update({'Detector type': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.input('Detector Geometrical Size', value=self.system.hw_profile.get('Detector size', ''), on_change=lambda e: self.system.hw_profile.update({'Detector size': e.value})).props('dense outlined').classes('flex-1 text-xs')
                    ui.input('Detector Factory S/N Code', value=self.system.hw_profile.get('Detector serial number', 'UNKNOWN'), on_change=lambda e: self.system.hw_profile.update({'Detector serial number': e.value})).props('dense outlined').classes('w-full text-xs')
                    ui.label('Energy Calibration Coefficients ($MCA_CAL Matrix Model)').classes('text-xs font-bold mt-2').style(f"color: {BRAND_COLORS['primary']};")
                    with ui.row().classes('w-full gap-2'):
                        ui.number('Offset / a0', value=self.system.hw_profile.get('calib_a0', 0.0), format='%.5f', on_change=lambda e: self.system.hw_profile.update({'calib_a0': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.number('Linear Slope / a1', value=self.system.hw_profile.get('calib_a1', 1.0), format='%.5f', on_change=lambda e: self.system.hw_profile.update({'calib_a1': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.number('Quadratic Scalar / a2', value=self.system.hw_profile.get('calib_a2', 0.0), format='%.3e', on_change=lambda e: self.system.hw_profile.update({'calib_a2': e.value})).props('dense outlined').classes('flex-1 text-xs')
            # RIGHT COLUMN: Advanced MCA settings Panel
            with ui.column().classes('gap-3 flex-1').style('width: 50%;'):
                with ui.card().classes('w-full p-4 rounded-lg border shadow-md bg-white space-y-3 h-full'):
                    ui.label('Advanced MCA settings').classes('text-xs font-bold uppercase tracking-wider text-zinc-700 border-b pb-1 w-full')
                    with ui.row().classes('w-full gap-3'):
                        ui.number('Coarse VGA Analog Gain', value=self.system.hw_profile.get('vga_gain_coarse', 4.0), format='%.2f', on_change=lambda e: self.system.hw_profile.update({'vga_gain_coarse': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.number('Channel Filter Smoothing Factor', value=self.system.hw_profile.get('smoothing_factor', 2), format='%d', on_change=lambda e: self.system.hw_profile.update({'smoothing_factor': int(e.value or 2)})).props('dense outlined').classes('flex-1 text-xs')
                    with ui.row().classes('w-full gap-3'):
                        ui.number('Shaper Peaking Time (s)', value=self.system.hw_profile.get('shaper_s_tau_pk', 2.5e-6), format='%.3e', on_change=lambda e: self.system.hw_profile.update({'shaper_s_tau_pk': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.number('Shaper Flat Top (s)', value=self.system.hw_profile.get('shaper_s_tau_pk_top', 1.0e-6), format='%.3e', on_change=lambda e: self.system.hw_profile.update({'shaper_s_tau_pk_top': e.value})).props('dense outlined').classes('flex-1 text-xs')
                    with ui.row().classes('w-full gap-3'):
                        ui.number('Detector Decay Tau_d (s)', value=self.system.hw_profile.get('tau_d', 1.21e-6), format='%.3e', on_change=lambda e: self.system.hw_profile.update({'tau_d': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.number('Detector Rise Tau_r (s)', value=self.system.hw_profile.get('tau_r', 0.206e-6), format='%.3e', on_change=lambda e: self.system.hw_profile.update({'tau_r': e.value})).props('dense outlined').classes('flex-1 text-xs')
                    with ui.row().classes('w-full gap-3 items-center justify-between'):
                        ui.number('BLR Threshold Gain', value=self.system.hw_profile.get('blr_s_threshold_gain', 4.0), format='%.2f', on_change=lambda e: self.system.hw_profile.update({'blr_s_threshold_gain': e.value})).props('dense outlined').classes('flex-1 text-xs')
                        ui.checkbox('Invert Pulse Polarity', value=self.system.hw_profile.get('invert_pulse', False), on_change=lambda e: self.system.hw_profile.update({'invert_pulse': e.value})).classes('text-xs text-zinc-700 font-medium px-1')

        with ui.row().classes('w-full mt-3 justify-end'):
            def save_calibration_profile_to_database():
                self.system.db[self.system.serial_number] = {k: v for k, v in self.system.hw_profile.items()}
                if self.system.save_hardware_db():
                    ui.notify("Calibration permanently saved!", type="positive")
            ui.button('COMMIT CALIBRATION PARAMETERS', icon='save', on_click=save_calibration_profile_to_database).style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").classes('py-2 px-4 text-xs shadow-md rounded-md')
