"""
Instructions:
    - Scroll down to the end of this file
    - Inspect how the library is used in the `if __name__ == "__main__":` block
    - Import this module into your library or directly run this script
        + To import: `from dpp_parameters import Dpp_Parameters`
    - Requirements: fixedpoint, numpy
"""

__authors__ = "Ivan Morales, Mladen Bogovac"
__license__ = "MIT"
__version__ = "1.1"
__date__ = "2026-05-25"

from fixedpoint import FixedPoint
import numpy as np
import math

class FixedPoint_Bin:
    def __new__(cls, val : int, signed : bool, m : int, n : int, return_binary_str : bool = False, *args, **kwargs):
        """Used to compute a FixedPoint representation of a floating-point number.
        
        Args:
            val (int): Value/number to be converted into fixed point and returned as padded binary
            signed (bool): Whether the fixed point number is signed or not
            m (int): Number of integer bits in the fixed point number
            n (int): Number of fractional bits in the fixed point number
            return_binary_str (bool): Whether return a binary string or a 32-bit unsigned representation. Defaults to False (return uint32_t).
            *args: Variable length argument list to be passed to the underlying FixedPoint object
            **kwargs: Arbitrary keyword arguments to be passed to the underlying FixedPoint object

        Returns:
            FixedPoint_Bin: The fixed point binary representation of the provided `val` with added leading zeros
        """
        q = m + n
        fixed_point_val = FixedPoint(val, signed = signed, m = m, n = n, *args, **kwargs)
        fixed_point_val = cls.padded_bin(fixed_point_val, q)

        if return_binary_str:
            return fixed_point_val
        return int(fixed_point_val, 2)
    
    @classmethod
    def padded_bin(cls, val, len_bits):
        """Pads a binary string with leading zeros to a specified length
        
        Args:
            val (int): The value to be converted to a binary string
            len_bits (int): The desired length of the binary string
            
        Returns:
            str: The padded binary string
        """
        bin_digits = bin(val).lstrip("0b") # remove '0b' from beginning of str
        num_bin_chars = len(bin_digits)
        if num_bin_chars > len_bits:
            raise ValueError(f"Value {val} is too large to fit in {len_bits} bits. Required: {num_bin_chars} bits.")

        #: Compute amount of leading zeros (if any)
        extra_zeros = '0' * (len_bits - num_bin_chars)

        #: Binary zero padding in most significant bits
        bin_digits = extra_zeros + bin_digits

        return bin_digits

class __Aux_Conversions:
    """
    Auxiliary methods to perform the opposite operations of the FixedPoint_Bin class.

    Used during development to validate existing 32-bit numbers from the original DPP configuration bits.
    """

    def signed_32_to_float(self, raw_int, total_bits, fractional_bits):
        """Converts a 32-bit signed integer into its floating-point representation.

        Args:
            raw_int (int): The 32-bit signed integer to be converted.
            total_bits (int): The total number of bits in the integer, including the sign bit (m+n).
            fractional_bits (int): The number of fractional bits in the integer (n).

        Returns:
            float: The floating-point representation of the input integer.
        """

        # Solve the 2-complement to interpret the sign
        if raw_int & (1 << (total_bits - 1)):  # Is the MSB 1?
            raw_int -= (1 << total_bits)       # In that case, convert to negative
            
        # Divide by 2^n to get the float value
        return raw_int / (1 << fractional_bits)


    def unsigned_32_to_float(self, raw_int, fractional_bits):
        """Converts a 32-bit unsigned integer into its floating-point representation.

        Args:
            raw_int (int): The 32-bit unsigned integer to be converted.
            fractional_bits (int): The number of fractional bits in the integer (n).

        Returns:
            float: The floating-point representation of the input integer.
        
        """
        # Equivalent operation to raw_int / 2^n, being n = fractional_bits
        return raw_int / (1 << fractional_bits)

class __Dpp_Common:

    def __init__(self, sampling_rate : float):
        """
        Shared parameters among DPP parameters computation modules.

        Args:
            sampling_rate (float): Sampling rate of the signal (Hz)
        """
        self.sampling_rate = sampling_rate
        self.t_clk = 1.0/sampling_rate

    def _compute_na(self, tau_pk : float):
        return np.ceil(tau_pk/self.t_clk)
    
    def _compute_nb(self, tau_pk : float, tau_pk_top : float):
        return np.ceil((tau_pk+tau_pk_top)/self.t_clk)
    
    def _to_nanoseconds(self, value_seconds : float) -> float:
        return value_seconds * 1e9
    
    def _to_milliseconds(self, value_seconds: float) -> float:
        return value_seconds * 1e3

class Dpp_Shaper(__Dpp_Common):

    BNA = 10 #: Related to maximum value of peaking time
    BNB = 10 #: Related to maximum value of peaking time + flat top time
    def __init__(self, 
                sampling_rate : float,
                tau_d : float,
                tau_r : float,
                tau_l : float,
                tau_pk : float,
                tau_pk_top: float,
                poles : int = 2,
                gain : int = 1,
                # dc_offset : float = 0.0, ## Deprecated. Apply offset in Formatter module.
                # invert_pulse : bool = False, ## Deprecated. Apply polarity inversion in Formatter.
                dc_offset_at_filter_input : float = 0.0,
                dc_offset_at_filter_output : float = 0.0,):
        """
        Pulse shaper parameters computation. Used for both fast and slow shapers in the DPP.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_d (float): Decay time constant of the detector (in seconds)
            tau_r (float): Rise time constant of the detector (in seconds)
            tau_l (float): Long undershoot constant (for PMT only)
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            poles (int, optional): Number of poles in the filter. Defaults to 2. It must be either 2 or 3.
            gain (int, optional): Digital gain to apply after shaping. Defaults to 1.
            dc_offset (float, optional): Signal input DC offset. Defaults to 0.0.
            invert_pulse (bool, optional): Invert original pulse before shaping. Defaults to False.
            dc_offset_at_filter_input (float, optional): 3-pole filter DC offset input. Defaults to 0.0.
            dc_offset_at_filter_output (float, optional): 3-pole filter DC offset output. Defaults to 0.0.
        """

        SHAPER_DC_OFFSET = 0.00
        SHAPER_INVERT_PULSE = False

        super().__init__(sampling_rate = sampling_rate)
        tau_s = tau_r
        tau_f = tau_d
        t_clk = self.t_clk
        self.tau_d = tau_d #: Decay time constant
        self.tau_f = tau_d #: Same as tau_d 
        self.tau_r = tau_r #: Rise time constant
        self.tau_s = tau_s #: Alias for rise time (see Mladen's Matlab simulation)
        self.tau_l = tau_l #: Long undershoot constant (for PMT only)
        self.poles = poles #: Number of poles in the filter
        self.tau_pk = tau_pk #: Peaking time
        self.tau_pk_top = tau_pk_top #: Flat top time
        self.dc_offset = SHAPER_DC_OFFSET #: Signal input DC offset
        self.invert_pulse = SHAPER_INVERT_PULSE #: Invert original pulse before shaping
        self.dc_offset_at_filter_input = dc_offset_at_filter_input #: 3-pole filter DC offset input
        self.dc_offset_at_filter_output = dc_offset_at_filter_output #: 3-pole filter DC offset output

        if gain <= 0:
            gain = 1
        self.gain = gain #: Digital gain to apply after shaping
        
        # Pre-computing common parameters in the shaper implementation
        self._as = -1.0/(tau_s*(1.0/tau_l-1.0/tau_s)*(1.0/tau_f-1.0/tau_s))
        self._al = -1.0/(tau_l*(1.0/tau_f-1.0/tau_l)*(1.0/tau_s-1.0/tau_l))
        self._af = -1.0/(tau_f*(1.0/tau_s-1.0/tau_f)*(1.0/tau_l-1.0/tau_f))

        self.al2 = -1.0/(tau_l*(1.0/tau_f-1.0/tau_l))
        self.af2 = -1.0/(tau_f*(1.0/tau_l-1.0/tau_f))

        self.exp_s = np.exp(-t_clk/tau_s)
        self.exp_l = np.exp(-t_clk/tau_l)
        self.exp_f = np.exp(-t_clk/tau_f)

        self.b21 = self.exp_s

        self.na = self._compute_na(tau_pk=tau_pk)
        self.nb = self._compute_nb(tau_pk=tau_pk, tau_pk_top=tau_pk_top)

        #: Check whether the required poles are right: 2 or 3 are accepted only
        assert (self.poles == 2 or self.poles == 3), "The filter must be defined either as a 2-pole or 3-pole implementation"

        #: b22 parameter based on poles
        self.b22 = 0 if self.poles == 2 else self.exp_l

        #: Computing shaper parameters based on user input
        #: User can access to them as class parameters just after instantiation
        self.r1_b10_32_0 = self._compute_r1_b10()
        self.r2_na_inv_32_0 = self._compute_r2_na_inv()
        self.r3_na_32_0 = self._compute_r3_na()
        self.r4_nb_32_0 = self._compute_r4_nb()
        self.r5_b20_32_0 = self._compute_r5_b20()
        self.r6_dc_offset_1_32_0 = self._compute_r6_dc_offset_1()
        self.r7_b2_32_0 = self._compute_r7_b2()
        self.r8_b1_32_0 = self._compute_r8_b1()
        self.r9_aa20_32_0 = self._compute_r9_aa20()
        self.r10_flags_32_0 = self._compute_r10_flags()
        self.r11_offset_2_32_0 = self._compute_r11_offset_2()
        self.r12_delay_line_32_0 = self._compute_r12_delay_line()

        self.params_dict = {
            'r1_b10_32_0'           : self.r1_b10_32_0,
            'r2_na_inv_32_0'        : self.r2_na_inv_32_0,
            'r3_na_32_0'            : self.r3_na_32_0,
            'r4_nb_32_0'            : self.r4_nb_32_0,
            'r5_b20_32_0'           : self.r5_b20_32_0,
            'r6_dc_offset_1_32_0'   : self.r6_dc_offset_1_32_0,
            'r7_b2_32_0'            : self.r7_b2_32_0,
            'r8_b1_32_0'            : self.r8_b1_32_0,
            'r9_aa20_32_0'          : self.r9_aa20_32_0,
            'r10_flags_32_0'        : self.r10_flags_32_0,
            'r11_offset_2_32_0'     : self.r11_offset_2_32_0,
            # 'r12_delay_line_32_0'   : self.r12_delay_line_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 17 parameters in the following order:
        - Tclk
        - Taur
        - Taud
        - Taupk
        - Taupk_top
        - Gain 
        - b10
        - na_inv
        - na
        - nb
        - b20
        - dc_offset
        - b2
        - b1
        - aa20
        - flags
        - dc_offset_2
        """
        self.params_daq : list = [
            # Tclk (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.t_clk), False, 32, 0), 

            # Taur (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.tau_r), False, 32, 0), 

            # Taud (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.tau_d), False, 32, 0), 

            # Taupk (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.tau_pk), False, 32, 0), 

            # Taupk_top (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.tau_pk_top), False, 32, 0),

            # Gain (dimensionless): U - Q1.25
            FixedPoint_Bin(self.gain, False, 1, 25),

            # Registers have been previously computed in their Qm.n format
            self.r1_b10_32_0, #b10
            self.r2_na_inv_32_0, #na_inv
            self.r3_na_32_0, #na
            self.r4_nb_32_0, #nb
            self.r5_b20_32_0, #b20
            self.r6_dc_offset_1_32_0, #dc_offset_1
            self.r7_b2_32_0, #b2
            self.r8_b1_32_0, #b1
            self.r9_aa20_32_0, #aa20
            self.r10_flags_32_0, #flags
            self.r11_offset_2_32_0, #dc_offset_2
        ]


    def _compute_r1_b10(self):
        b10 = np.exp(-self.t_clk/self.tau_d)
        return FixedPoint_Bin(b10, False, 7, 25)
    
    def _compute_r3_na(self):
        nad = self.na - 3
        return FixedPoint_Bin(nad, False, 32, 0)
    
    def _compute_r2_na_inv(self):
        na_inv = 1.0/self.na
        na_inv *= self.gain #: Apply the output gain
        return FixedPoint_Bin(na_inv, False, 14, 18)
    
    def _compute_r4_nb(self):
        nbd = self.nb - 3
        return FixedPoint_Bin(nbd, False, 32, 0)
    
    def _compute_r5_b20(self):
        """
        Compute normalization coefficient b20 for both implementations: 3-pole and 2-pole shaper
        """

        # Aliases to simplify equation reading/debugging
        tauf = self.tau_f
        taus = self.tau_s
        taul = self.tau_l
        tclk = self.t_clk
        exp = np.exp
        log = np.log
        ceil = np.ceil
        floor = np.floor
        a_s = self._as
        a_l = self._al
        a_f = self._af
        expl = self.exp_l
        expf = self.exp_f
        exps = self.exp_s

        if self.poles == 2:
            p2_tpeak = tauf*taus/(tauf-taus)*log(tauf/taus)
            p2_m = p2_tpeak/tclk
            p2_m1 = ceil(p2_m)
            p2_m2 = floor(p2_m)
            p2_a1 = exp(-p2_m1*tclk/tauf)-exp(-p2_m1*tclk/taus)
            p2_a2 = exp(-p2_m2*tclk/tauf)-exp(-p2_m2*tclk/taus)
            if(p2_a1>p2_a2):
                p2_norm_digital_numerator = p2_a1
            else:
                p2_norm_digital_numerator = p2_a2
            
            p2_norm_digital_denominator=exp(-tclk/tauf)-exp(-tclk/taus)
            p2_norm_digital=(p2_norm_digital_numerator/p2_norm_digital_denominator)

            b20 = p2_norm_digital
        
        elif self.poles == 3:
            p3_m = (taus/tclk)*log(tauf/taus)
            p3_m1 = ceil(p3_m)
            p3_m2 = floor(p3_m)
            p3_a1=a_s*exp(-(p3_m1*tclk)/taus)+a_l*exp(-(p3_m1*tclk)/taul)+a_f*exp(-(p3_m1*tclk)/tauf)
            p3_a2=a_s*exp(-(p3_m2*tclk)/taus)+a_l*exp(-(p3_m2*tclk)/taul)+a_f*exp(-(p3_m2*tclk)/tauf)
            p3_an=a_s*(expl+expf)+a_l*(expf+exps)+a_f*(exps+expl)
            if(p3_a1>p3_a2):
                p3_norm_digital = -p3_a1/p3_an
            else:
                p3_norm_digital = -p3_a2/p3_an

            b20 = p3_norm_digital
    
        return FixedPoint_Bin(b20, False, 4, 21)
    
    def _compute_r6_dc_offset_1(self):
        signal_offset = self.dc_offset
        dc_offset_1 = signal_offset - self.dc_offset_at_filter_input
        return FixedPoint_Bin(dc_offset_1, True, 2, 14)
    
    def _compute_r7_b2(self):
        b2 = self.b22*self.b21
        return FixedPoint_Bin(b2, False, 0, 25)
    
    def _compute_r8_b1(self):
        b1 = self.b22+self.b21
        return FixedPoint_Bin(b1, False, 1, 24)
    
    def _compute_r9_aa20(self):
        # Aliases to simplify equation reading/debugging
        al2 = self.al2
        af2 = self.af2
        expl = self.exp_l
        expf = self.exp_f

        if self.poles == 2:
            aa20 = 0
        else:
            aa20_d = al2*expf+af2*expl
            aa20_n = al2+af2
            aa20 = aa20_d/aa20_n

        kk = 25
        return FixedPoint_Bin(aa20, False, 0, kk)
    
    def _compute_r10_flags(self):
        flags = int(self.invert_pulse)
        return FixedPoint_Bin(flags, False, 32, 0)
    
    def _compute_r11_offset_2(self):
        dc_offset_2 = 0.0 #?
        return FixedPoint_Bin(dc_offset_2, True, 10, 14)
    
    def _compute_r12_delay_line(self):
        delay = np.ceil((2*self.tau_pk + self.tau_pk_top)/self.t_clk)
        return FixedPoint_Bin(delay, False, 10, 0)
    
    def __str__(self):
        return f"Pulse shaper: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()
    

class Dpp_Blr_Slow(__Dpp_Common):

    TAU_BLR_CHARGE = 0.001 # In seconds
    TAU_BLR_DISCHARGE = 0.05 # Seconds
    
    def __init__(self, 
                sampling_rate : float,
                tau_pk : float,
                tau_pk_top: float,
                blr_speed_conf_bits : int = 3,
                threshold_high : float = 0.00,
                threshold_low : float = -0.05,
                threshold_gain : float = 2.0,
                threshold_low_gain : float = 2.0,
                ):
        """
        Baseline restorer parameters computation. Slow BLR module used in the DPP.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            blr_speed_conf_bits (int, optional): BLR speed configuration bits (m) m = 3 tau_blr = 1.31 ms, m = 2 tau_blr = 81.9 us, m = 1 tau_blr = 10.2 us, m = 0 tau_blr = 1.28 us. Defaults to 3.
            threshold_high (float): BLR clamping high threshold in Volts. Defaults to 0.00.
            threshold_low (float): BLR clamping low threshold in Volts. Defaults to -0.05.
            threshold_gain (float, optional): Gain for high threshold. Defaults to 2.0.
            threshold_low_gain (float, optional): Gain for low threshold. Defaults to 2.0.
        """
        super().__init__(sampling_rate = sampling_rate)
        self.threshold_low = threshold_low
        self.threshold_high = threshold_high
        self.threshold_gain = threshold_gain
        self.threshold_low_gain = threshold_low_gain
        self.blr_speed_conf_bits = blr_speed_conf_bits
        self.na = self._compute_na(tau_pk=tau_pk)
        self.nb = self._compute_nb(tau_pk=tau_pk, tau_pk_top=tau_pk_top)
        self.tau_pk = tau_pk #: Peaking time
        self.tau_pk_top = tau_pk_top #: Flat top time
        
        self.r1_threshold_32_0 = self._compute_r1_threshold()
        self.r2_flags_32_0 = self._compute_r2_flags()
        self.r3_threshold_gain_32_0 = self._compute_r3_threshold_gain()
        self.r4_preset_32_0 = self._compute_r4_preset()
        self.r5_b0_32_0 = self._compute_r5_b0()
        self.r6_a1_32_0 = self._compute_r6_a1()
        self.r7_threshold_low_gain_32_0 = self._compute_r7_threshold_low_gain()
        self.r8_delay_line_32_0 = self._compute_r8_delay_line()

        self.params_dict = {
            'r1_threshold_32_0'             : self.r1_threshold_32_0,
            'r2_flags_32_0'                 : self.r2_flags_32_0,
            'r3_threshold_gain_32_0'        : self.r3_threshold_gain_32_0,
            'r4_preset_32_0'                : self.r4_preset_32_0,
            'r5_b0_32_0'                    : self.r5_b0_32_0,
            'r6_a1_32_0'                    : self.r6_a1_32_0,
            'r7_threshold_low_gain_32_0'    : self.r7_threshold_low_gain_32_0,
            'r8_delay_line_32_0'            : self.r8_delay_line_32_0 
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 7 parameters in the following order:
        - Threshold (high | low)
        - Flags
        - Threshold_gain
        - Preset
        - b0
        - a1
        - Threshold_low_gain
        """
        self.params_daq : list = [
            self.r1_threshold_32_0,
            self.r2_flags_32_0,
            self.r3_threshold_gain_32_0,
            self.r4_preset_32_0,
            self.r5_b0_32_0,
            self.r6_a1_32_0,
            self.r7_threshold_low_gain_32_0
        ]
        
    def _compute_r1_threshold(self):
        # Threshold clamping value must be negative
        thr_lo = self.threshold_low
        thr_lo_bits = FixedPoint_Bin(thr_lo, True, 2, 14)

        # Threshold offset value must ve positive (or at least 0)
        thr_hi = self.threshold_high
        thr_hi_bits = FixedPoint_Bin(thr_hi, True, 2, 14)

        return (thr_lo_bits | thr_hi_bits<<16)
    
    def _compute_r2_flags(self):
        ## define bits bit_1_2: 'm' 
        ## m defines blr speed, how fast baseline goes to zero exp(-n*Tclk/tau_blr)
        ## default value is m=3
        ## m = 3 tau_blr = 1.31 msec @ Tclk=20e-9 = 50MHz, 1/2^16
        ## m = 2 tau_blr = 81.9 usec @ Tclk=20e-9 = 50MHz, 1/2^12
        ## m = 1 tau_blr = 10.2 usec @ Tclk=20e-9 = 50MHz, 1/2^9   
        ## m = 0 tau_blr = 1.28 usec @ Tclk=20e-9 = 50MHz, 1/2^6 
        
        ## bit_0 = 1 blr is disabled and correction is 0 (blr not used, accumulator is in reset state)
        ## bit_0 = 0 blr is enabled
        ## bit_1,2 = m

        if self.blr_speed_conf_bits not in [0,1,2,3]:
            raise ValueError(f"Invalid BLR speed configuration bits. Expected [0,1,2,3], got {self.blr_speed_conf_bits}")
        
        flags = self.blr_speed_conf_bits << 1

        return FixedPoint_Bin(flags, False, 32, 0)
    
    def _compute_r3_threshold_gain(self):
        return FixedPoint_Bin(self.threshold_gain, False, 8, 8)
        
    def _compute_r4_preset(self):
        PRECISION = 10 # This amount of bits may not be enough for longer tau_pk and tau_pk_top

        preset_look_ahead = 2*self.na + self.nb
        preset_trail = np.ceil(0.5*self.na)
        preset_limit = 3*preset_look_ahead

        preset_look_ahead   = np.clip(preset_look_ahead, 0, 2**PRECISION - 1)
        preset_trail        = np.clip(preset_trail, 0, 2**PRECISION - 1)
        preset_limit        = np.clip(preset_limit, 0, 2**PRECISION - 1)

        preset_hi = FixedPoint_Bin(preset_trail, False, PRECISION, 0)
        preset_mid = FixedPoint_Bin(preset_limit, False, PRECISION, 0)
        preset_lo = FixedPoint_Bin(preset_look_ahead, False, PRECISION, 0)

        return preset_hi << PRECISION*2 | preset_mid << PRECISION | preset_lo

    def _compute_r5_b0(self):
        b0 = 2*self.t_clk/self.TAU_BLR_CHARGE
        return FixedPoint_Bin(b0, False, 0, 32)
    
    def _compute_r6_a1(self):
        a1 = 1.0-(2*self.t_clk/self.TAU_BLR_DISCHARGE)
        return FixedPoint_Bin(a1, False, 0, 32)

    def _compute_r7_threshold_low_gain(self):
        thrshld_low_gain = self.threshold_low_gain
        return FixedPoint_Bin(thrshld_low_gain, False, 8, 8)
    
    ## Deprecated, not used in DAQ/MCA implementation
    def _compute_r8_delay_line(self):
        delay = np.ceil((2*self.tau_pk + self.tau_pk_top)/self.t_clk)
        return FixedPoint_Bin(delay, False, 10, 0)
    
    def __str__(self):
        return f"BLR slow: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()


class Dpp_Pk_Detector_Slow(__Dpp_Common):

    TAU_BLR_CHARGE = 100e-6 # 100 us
    TAU_BLR_DISCHARGE = 1000e-6 # 1 ms
    FLAGS = 1
    
    def __init__(self, 
                sampling_rate : float,
                tau_pk : float,
                tau_pk_top: float,
                blanking_time_factor : float = 0.9,
                time_over_thrshld_factor : float = 0.44,
                x_min : float = 0.01,
                x_max : float = 1.99,
                ):
        """
        Peak detector parameters computation. Slow peak detector used to extract the
        event energy in the DPP.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top duration (in seconds)
            blanking_time_factor (float, optional): Blanking time factor (look ahead). Defaults to 0.9.
            time_over_thrshld_factor (float, optional): Time over threshold factor. Defaults to 0.44.
            x_min (float, optional): Minimum value for the output. Defaults to 0.01.
            x_max (float, optional): Maximum value for the output. Defaults to 1.99.
        """
        super().__init__(sampling_rate = sampling_rate)
        self.blanking_time_factor = blanking_time_factor
        self.time_over_thrshld_factor = time_over_thrshld_factor
        self.tau_pk = tau_pk
        self.tau_pk_top = tau_pk_top
        self.x_min = x_min
        self.x_max = x_max

        self.r1_blanking_time_32_0 = self._compute_r1_blanking_time()
        self.r2_time_over_threshold_32_0 = self._compute_r2_time_over_threshold()
        self.r3_x_min_32_0 = self._compute_r3_xmin()
        self.r4_x_max_32_0 = self._compute_r4_xmax()
        self.r5_flags_32_0 = self._compute_r5_flags()

        self.params_dict = {
            'r1_blanking_time_32_0'         : self.r1_blanking_time_32_0,
            'r2_time_over_threshold_32_0'   : self.r2_time_over_threshold_32_0,
            'r3_x_min_32_0'                 : self.r3_x_min_32_0,
            'r4_x_max_32_0'                 : self.r4_x_max_32_0,
            'r5_flags_32_0'                 : self.r5_flags_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 6 parameters in the following order:
        - Tclk
        - Blanking_time
        - Time_over_threshold
        - x_min_slow
        - x_max_slow
        - flags
        """
        self.params_daq : list = [
            # Tclk (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.t_clk), False, 32, 0), 
            self.r1_blanking_time_32_0, # blanking_time
            self.r2_time_over_threshold_32_0, # time_over_threshold
            self.r3_x_min_32_0, # x_min
            self.r4_x_max_32_0, # x_max
            self.r5_flags_32_0 # flags
        ]


    def _compute_r1_blanking_time(self):
        blanking_time = np.ceil(self.blanking_time_factor*self.tau_pk/self.t_clk)
        return FixedPoint_Bin(blanking_time, False, 32, 0)
    
    def _compute_r2_time_over_threshold(self):
        tot_factor = self.time_over_thrshld_factor
        tot = np.ceil((self.tau_pk_top + tot_factor*self.tau_pk)/self.t_clk)
        return FixedPoint_Bin(tot, False, 32, 0)
    
    def _compute_r3_xmin(self):
        return FixedPoint_Bin(self.x_min, True, 2, 14)
    
    def _compute_r4_xmax(self):
        return FixedPoint_Bin(self.x_max, True, 2, 14)

    def _compute_r5_flags(self):
        return FixedPoint_Bin(self.FLAGS, False, 32, 0)
    
    def __str__(self):
        return f"Peak detector slow: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()
    
class Dpp_Scope(__Dpp_Common):

    # No other trigger modes supported in this firmware version
    DEFAULT_TRIGGER_MODE = 0

    def __init__(self,
                 sampling_rate : float,
                 bram_size : int,
                 threshold : float,
                 delay : int,
                 enable : bool,
                 clear : bool,
                 downsample_factor : int,
                 sampling_mode : int,
                 ):
        """
        Integrated oscilloscope module configuration.

        Args:
            sampling_rate (float): Sampling rate of the ADC (in Hz)
            bram_size (int): Size of the BRAM to store the traces (in samples)
            threshold (float): Trigger threshold (in Volts)
            delay (int): Trigger delay (in sample units)
            enable (bool): Is the oscilloscope enabled upon startup?
            clear (bool): Clear trigger before starting
            downsample_factor (int): Downsampling factor - valid values are 1, 2, 3, 4
            sampling_mode (int): Sampling mode - 0: Decimate, 1: Max between two samples, 2: Min between two samples
        """


        super().__init__(sampling_rate = sampling_rate)
        self.bram_size = bram_size
        self.threshold = threshold
        self.delay = delay
        self.enable = enable
        self.clear = clear
        self.full = 1 # Set the full flag on startup. DEPRECATED.
        self.downsample = self.__validate_downsampling(downsample_factor)
        self.sampling_mode = self.__validate_sampling_mode(sampling_mode)
        self.trigger_mode = self.DEFAULT_TRIGGER_MODE # Not supported in this firmware version

        self.r1_bram_size_32_0 = self._compute_r1_bram_size()
        self.r2_threshold_32_0 = self._compute_r2_threshold()
        self.r3_delay_32_0 = self._compute_r3_delay()
        self.r4_enable_32_0 = self._compute_r4_enable()
        self.r5_clear_32_0 = self._compute_r5_clear()
        self.r6_full_32_0 = self._compute_r6_full()
        self.r7_downsample_32_0 = self._compute_r7_downsample()
        self.r8_sampling_mode_32_0 = self._compute_r8_sampling_mode()
        self.r9_trigger_mode_32_0 = self._compute_r9_trigger_mode()

        self.params_dict = {
            'r1_bram_size_32_0'         : self.r1_bram_size_32_0,
            'r2_threshold_32_0'         : self.r2_threshold_32_0,
            'r3_delay_32_0'             : self.r3_delay_32_0,
            'r4_enable_32_0'            : self.r4_enable_32_0,
            'r5_clear_32_0'             : self.r5_clear_32_0,
            'r6_full_32_0'              : self.r6_full_32_0,
            'r7_downsample_32_0'        : self.r7_downsample_32_0,
            'r8_sampling_mode_32_0'     : self.r8_sampling_mode_32_0,
            'r9_trigger_mode_32_0'      : self.r9_trigger_mode_32_0
        }


        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 10 parameters in the following order:
        - Tclk
        - BRAM_Size
        - Threshold
        - Delay
        - Enable
        - Clear
        - Full
        - Downsample
        - Sampling_Mode
        - Trigger_Mode
        """
        self.params_daq : list = [
            # Tclk (nanoseconds): U - Q32.0
            FixedPoint_Bin(self._to_nanoseconds(self.t_clk), False, 32, 0), 

            self.r1_bram_size_32_0, # bram_size
            self.r2_threshold_32_0, # threshold
            self.r3_delay_32_0, # delay
            self.r4_enable_32_0, # enable
            self.r5_clear_32_0, # clear
            self.r6_full_32_0, # full
            self.r7_downsample_32_0, # downsample            
            self.r8_sampling_mode_32_0, # sampling_mode
            self.r9_trigger_mode_32_0, # trigger_mode
        ]

    def __validate_downsampling(self, ds_factor : int) -> int:
        ds_factor = int(ds_factor) # Validate a valid integer is used
        if ds_factor < 1 or ds_factor > 4:
            ds_mode = 4 # No downsampling (see Dpp_parameters.pdf)
        else:
            ds_mode = ds_factor + 4 # Enable downsampling with desired factor

        return ds_mode


    def __validate_sampling_mode(self, sampling_mode : int) -> int:
        OFFST_CH1 = 0x00
        OFFST_CH2 = 0x02
        OFFST_TRG = 0x04
        
        s_mode = int(sampling_mode)
        if s_mode > 2 or s_mode < 0: # See bit masks in documentation
            return 21 # Default value: all channels to 0x01
        
        # Otherwise, set the proper mode to all the channels, including trigger
        s_mode : int = s_mode*(2**OFFST_CH1 + 2**OFFST_CH2 + 2**OFFST_TRG)
        
        return s_mode
    
    def _compute_r1_bram_size(self):
        return FixedPoint_Bin(self.bram_size, False, 32, 0)
    
    def _compute_r2_threshold(self):
        return FixedPoint_Bin(self.threshold, True, 2, 14)
    
    def _compute_r3_delay(self):
        return FixedPoint_Bin(self.delay, False, 32, 0)
    
    def _compute_r4_enable(self):
        if self.enable:
            return 1
        return 0
    
    def _compute_r5_clear(self):
        if self.clear:
            return 1
        return 0
    
    def _compute_r6_full(self):
        if self.full:
            return 1
        return 0
    
    def _compute_r7_downsample(self):
        return FixedPoint_Bin(self.downsample, False, 32, 0)
    
    def _compute_r8_sampling_mode(self):
        return FixedPoint_Bin(self.sampling_mode, False, 32, 0)
    
    def _compute_r9_trigger_mode(self):
        return FixedPoint_Bin(self.trigger_mode, False, 32, 0)

    def __str__(self):
        return f"Scope: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()


class Dpp_Timers:

    def __init__(self,
                 tmr_preset_time : int = 10000000,
                 tmr_auto_mode : int = 0,
                 tmr_a_lt : bool = True,
                 tmr_b_lt : bool = False,
                 tmr_c_lt : bool = False,
                 tmr_a_en : bool = True,
                 tmr_b_en : bool = False,
                 tmr_c_en : bool = True,
                 tmr_a_clr: bool = False,
                 tmr_b_clr: bool = False,
                 tmr_c_clr: bool = False,
                 ):
        """
        Computation of the timer parameters to be sent to the DPP. 
        
        The timers measure the collection time of the spectrum (histogram).
        Three timers are available: A, B, and C. Each timer can be configured
        to count real time or live time. They can be disabled or enabled individually.
        Notice that **Timer C** controls the collection time and must be always enabled.

        Args:
            tmr_preset_time (int): Preset time for the collection of the spectrum (in milliseconds).
            tmr_auto_mode (int): 0 for manual mode, 1 for auto mode. Uses ping-pong memory access. Usually disabled.
            tmr_a_lt (bool): True for live time, False for real time.
            tmr_b_lt (bool): True for live time, False for real time.
            tmr_c_lt (bool): True for live time, False for real time.
            tmr_a_en (bool): True to enable timer A.
            tmr_b_en (bool): True to enable timer B.
            tmr_c_en (bool): True to enable timer C.
            tmr_a_clr (bool): True to clear timer A.
            tmr_b_clr (bool): True to clear timer B.
            tmr_c_clr (bool): True to clear timer C.
        """

        self.auto_mode = tmr_auto_mode
        self.tmr_a_lt = tmr_a_lt
        self.tmr_b_lt = tmr_b_lt
        self.tmr_c_lt = tmr_c_lt
        self.tmr_a_en = tmr_a_en
        self.tmr_b_en = tmr_b_en
        self.tmr_c_en = tmr_c_en
        self.tmr_a_clr = tmr_a_clr
        self.tmr_b_clr = tmr_b_clr
        self.tmr_c_clr = tmr_c_clr

        self.r1_tmr_preset_32_0 = tmr_preset_time
        self.r2_tmr_flags_32_0 = self.__compute_r2_tmr_flags()

        self.params_dict = {
            'r1_tmr_preset_32_0'        : self.r1_tmr_preset_32_0,
            'r2_tmr_flags_32_0'         : self.r2_tmr_flags_32_0,
        }


        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 2 parameters in the following order:
        - Preset
        - Ctrl_bits (flags)
        """
        self.params_daq : list = [
            self.r1_tmr_preset_32_0, # bram_size
            self.r2_tmr_flags_32_0, # threshold
        ]

    def __compute_r2_tmr_flags(self) -> int:
        OFFSET_MAN_MODE = 0x00
        OFFSET_AUTO_MODE = 0x01
        OFFSET_TMR_C_LT = 0x02
        OFFSET_TMR_B_LT = 0x03
        OFFSET_TMR_A_LT = 0x04
        OFFSET_TMR_C_EN = 0x05
        OFFSET_TMR_B_EN = 0x06
        OFFSET_TMR_A_EN = 0x07
        OFFSET_TMR_C_CLR = 0x08
        OFFSET_TMR_B_CLR = 0x09
        OFFSET_TMR_A_CLR = 0x0A
        
        man_mode : bool = not bool(self.auto_mode)

        flags = 0
        flags |= int(man_mode) << OFFSET_MAN_MODE
        flags |= int(self.auto_mode) << OFFSET_AUTO_MODE
        flags |= int(self.tmr_c_lt) << OFFSET_TMR_C_LT
        flags |= int(self.tmr_b_lt) << OFFSET_TMR_B_LT
        flags |= int(self.tmr_a_lt) << OFFSET_TMR_A_LT
        flags |= int(self.tmr_c_en) << OFFSET_TMR_C_EN
        flags |= int(self.tmr_b_en) << OFFSET_TMR_B_EN
        flags |= int(self.tmr_a_en) << OFFSET_TMR_A_EN
        flags |= int(self.tmr_c_clr) << OFFSET_TMR_C_CLR
        flags |= int(self.tmr_b_clr) << OFFSET_TMR_B_CLR
        flags |= int(self.tmr_a_clr) << OFFSET_TMR_A_CLR

        return flags
    
    def __str__(self):
        return f"Timers: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()

class Dpp_Scope_Mux:
    
    def __init__(self,
                 ch1 : int = 0,
                 ch2 : int = 0):
        
        """
        Scope input multiplexer module.

        Args:
            ch1 (int, optional): Channel 1 selection. Defaults to 0.
            ch2 (int, optional): Channel 2 selection. Defaults to 0.
        """
        
        self.ch1 = ch1
        self.ch2 = ch2

        self.r1_scopemux_32_0 = self._compute_r1_scopemux()

        self.params_dict = {
            'r1_scopemux_32_0' : self.r1_scopemux_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 1 parameter in the following order:
        - Scope mux (including CH2|CH1)
        """
        self.params_daq : list = [
            self.r1_scopemux_32_0
        ]

    def __validate_scope_channel(self, channel : int) -> int:
        channel = int(channel)
        if channel < 0 or channel > 3:
            channel = 0
        return channel

    def _compute_r1_scopemux(self):
        CH1_OFFSET = 0x00
        CH2_OFFSET = 0x04

        ch1 = self.__validate_scope_channel(self.ch1)
        ch2 = self.__validate_scope_channel(self.ch2)

        r1_scopemux = 0
        r1_scopemux |= ch1 << CH1_OFFSET
        r1_scopemux |= ch2 << CH2_OFFSET

        return r1_scopemux
    
    def __str__(self):
        return f"Scope Mux: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()
        
class Dpp_Blr_Fast(__Dpp_Common):

    TAU_BLR_CHARGE = 1e-3 # 1 ms
    TAU_BLR_DISCHARGE = 50e-3 # 50 ms
    
    def __init__(self, 
                sampling_rate : float,
                tau_pk : float,
                tau_pk_top: float,
                blr_speed_conf_bits : int = 2,
                threshold_high : float = 0.0,
                threshold_low : float = -0.1,
                threshold_gain : float = 6.0,
                threshold_low_gain : float = 2.0,
                ):
        """
        Fast BLR module parameters computation. Used in pile-up rejection subsystem.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            blr_speed_conf_bits (int, optional): BLR speed configuration bits (m) m = 3 tau_blr = 1.31 ms, m = 2 tau_blr = 81.9 us, m = 1 tau_blr = 10.2 us, m = 0 tau_blr = 1.28 us. Defaults to 2.
            threshold_high (float, optional): High threshold. Defaults to 0.0.
            threshold_low (float, optional): Low threshold. Defaults to -0.1.
            threshold_gain (float, optional): Gain for high threshold. Defaults to 6.0.
            threshold_low_gain (float, optional): Gain for low threshold. Defaults to 2.0.
        """
        super().__init__(sampling_rate = sampling_rate)
        self.threshold_low = threshold_low
        self.threshold_high = threshold_high
        self.threshold_gain = threshold_gain
        self.threshold_low_gain = threshold_low_gain
        self.blr_speed_conf_bits = blr_speed_conf_bits
        self.na = self._compute_na(tau_pk=tau_pk)
        self.nb = self._compute_nb(tau_pk=tau_pk, tau_pk_top=tau_pk_top)

        self.r1_threshold_32_0 = self._compute_r1_threshold()
        self.r2_flags_32_0 = self._compute_r2_flags()
        self.r3_threshold_gain_32_0 = self._compute_r3_threshold_gain()
        self.r4_b0_32_0 = self._compute_r4_b0()
        self.r5_a1_32_0 = self._compute_r5_a1()

        self.params_dict = {
            'r1_threshold_32_0'             : self.r1_threshold_32_0,
            'r2_flags_32_0'                 : self.r2_flags_32_0,
            'r3_threshold_gain_32_0'        : self.r3_threshold_gain_32_0,
            'r4_b0_32_0'                    : self.r4_b0_32_0,
            'r5_a1_32_0'                    : self.r5_a1_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 5 parameters in the following order:
        - Thresholds (high|low)
        - Flags
        - Threshold_gain
        - b0
        - a1
        """
        self.params_daq : list = [
            self.r1_threshold_32_0,
            self.r2_flags_32_0,
            self.r3_threshold_gain_32_0,
            self.r4_b0_32_0,
            self.r5_a1_32_0
        ]

    def _compute_r1_threshold(self):
        # Threshold clamping value must be negative
        thr_lo_bits = FixedPoint_Bin(self.threshold_low, True, 2, 14)

        # Threshold offset value must ve positive (or at least 0)
        thr_hi_bits = FixedPoint_Bin(self.threshold_high, True, 2, 14)

        return (thr_hi_bits<<16 | thr_lo_bits)
    
    def _compute_r2_flags(self):
        ## define bits bit_1_2: 'm' 
        ## m defines blr speed, how fast baseline goes to zero exp(-n*Tclk/tau_blr)
        ## default value is m=3
        ## m = 3 tau_blr = 1.31 msec @ Tclk=20e-9 = 50MHz, 1/2^16
        ## m = 2 tau_blr = 81.9 usec @ Tclk=20e-9 = 50MHz, 1/2^12
        ## m = 1 tau_blr = 10.2 usec @ Tclk=20e-9 = 50MHz, 1/2^9   
        ## m = 0 tau_blr = 1.28 usec @ Tclk=20e-9 = 50MHz, 1/2^6 

        ## bit_0 = 1 blr is disabled and correction is 0 (blr not used, accumulator is in reset state)
        ## bit_0 = 0 blr is enabled
        ## bit_1,2 = m
        if self.blr_speed_conf_bits not in [0,1,2,3]:
            raise ValueError(f"Invalid BLR speed configuration bits. Expected [0,1,2,3], got {self.blr_speed_conf_bits}")
        
        flags = self.blr_speed_conf_bits << 1

        return FixedPoint_Bin(flags, False, 32, 0)
    
    def _compute_r3_threshold_gain(self):
        return FixedPoint_Bin(self.threshold_gain, False, 8, 8)
    
    def _compute_r4_b0(self):
        b0 = self.t_clk/self.TAU_BLR_CHARGE
        return FixedPoint_Bin(b0, False, 0, 32)
    
    def _compute_r5_a1(self):
        a1 = 1.0-(self.t_clk/self.TAU_BLR_DISCHARGE)
        return FixedPoint_Bin(a1, False, 0, 32)
    
    def __str__(self):
        return f"BLR fast: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()

class Dpp_Pk_Detector_Fast(Dpp_Pk_Detector_Slow):

    def __init__(self, 
                sampling_rate : float,
                tau_pk : float,
                tau_pk_top: float,
                blanking_time_factor : float = 0.9,
                time_over_thrshld_factor : float = 0.44,
                x_min : float = 0.01,
                x_max : float = 1.99,
                ):
        """
        Fast peak detector parameters computation. Used in pile-up rejection subsystem.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            blanking_time_factor (float, optional): Blanking time factor. Defaults to 0.9.
            time_over_thrshld_factor (float, optional): Time over threshold factor. Defaults to 0.44.
            x_min (float, optional): Minimum amplitude value (volts). Defaults to 0.01.
            x_max (float, optional): Maximum amplitude value (volts). Defaults to 1.99.
        """
        super().__init__(sampling_rate = sampling_rate,
                         tau_pk=tau_pk,
                         tau_pk_top=tau_pk_top,
                         blanking_time_factor=blanking_time_factor,
                         time_over_thrshld_factor=time_over_thrshld_factor,
                         x_min=x_min,
                         x_max=x_max)

        ## `params_dict` and `params_list` are inherited from parent class

    def __str__(self):
        return f"Peak detector fast: {self.params_dict}"

    ## __repr__ is inherited from parent class

class Dpp_Formatter(__Dpp_Common):
    def __init__(self, 
                 sampling_rate : float,
                 dc_offset : float = 0.0,
                 invert_polarity : bool = False,
                 smoothing_factor : int = 1):
        
        """
        DPP Formatter (preprocessing) module parameters computation.
         
        Used to digitally manipulate the trace from the ADC prior to the DPP.
        Provides optional DC offset, polarity inversion and smoothing (moving average).

        Args:
            sampling_rate (float): Sampling rate of the ADC
            dc_offset (float, optional): DC offset to apply after ADC. Expected range: -2.0 to 2.0 Volts. Defaults to 0.0.
            invert_polarity (bool, optional): Invert polarity of the pulses. Defaults to False.
            smoothing_factor (int, optional): Smoothing factor (moving average). Valid 1, 2, 4, 8. Defaults to 1.
        """
        
        super().__init__(sampling_rate = sampling_rate)
        
        self.dc_offset = self.__validate_dc_offset(dc_offset)
        self.invert_polarity = bool(invert_polarity)
        self.smoothing_factor = self.__validate_smoothing(smoothing_factor)

        self.r1_dc_offset_32_0 = self._compute_r1_dc_offset()
        self.r2_flags_32_0 = self._compute_r2_flags()

        self.params_dict = {
            'r1_dc_offset_32_0' : self.r1_dc_offset_32_0,
            'r2_flags_32_0'     : self.r2_flags_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 2 parameters in the following order:
        - DC_offset
        - Flags
        """
        self.params_daq : list = [
            self.r1_dc_offset_32_0,
            self.r2_flags_32_0
        ]


    def _compute_r1_dc_offset(self):
        """
        Computes DC offset for the DPP formatter. Validation must be carried out
        before calling this method. Valid range is between -2.0 and 2.0 Volts.

        Returns:
            FixedPoint_Bin: DC offset
        """
        return FixedPoint_Bin(self.dc_offset, True, 2, 14)
    
    def _compute_r2_flags(self):
        """
        Computes the flags for the DPP formatter. Check the documentation
        for more details. 

        Flags: bit 0: Invert polarity
               bits 2-1: Smoothing factor
        """
        
        OFFSET_INVERT = 0x00
        OFFSET_SMOOTHING = 0x01
        
        flags = 0x00

        polarity = int(self.invert_polarity)
        s_factor = int(math.log2(self.smoothing_factor))

        flags |= polarity << OFFSET_INVERT
        flags |= s_factor << OFFSET_SMOOTHING

        return flags
    
    def __str__(self):
        return f"Formatter: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()
       

    def __validate_dc_offset(self, offset : float) -> float:
        """
        Checks the offset limits to be under the hardware specifications:
        between 2.0 and -2.0 Volts. Raises an exception otherwise.

        Args:
            offset (float): DC offset

        Returns:
            float: The validated DC offset
        
        Raises:
            ValueError: DC offset must be between -2.0 and 2.0 Volts
        """
        if offset >= 2.0 or offset <= -2.0:
            raise ValueError("DC offset must be between -2.0 and 2.0 Volts.")

        return offset

    def __validate_smoothing(self, s_factor : int):
        """
        Checks the smoothing factor to comply with the
        available options: x1, x2, x4, and x8.

        Args:
            s_factor (int): Smoothing factor

        Returns:
            int: The validated smoothing factor

        Raises:
            ValueError: Smoothing factor must be exclusively 1, 2, 4, or 8
        """

        s_factor = int(s_factor)
        if s_factor not in [1, 2, 4, 8]:
            raise ValueError("Smoothing factor must be exclusively 1, 2, 4, or 8.")
        return s_factor


class Dpp_Pileup_Rejector(__Dpp_Common):
    def __init__(self,
                 sampling_rate : float,
                 shaper_s_tau_pk : float,
                 shaper_s_tau_pk_top : float,
                 shaper_f_tau_pk : float,
                 shaper_f_tau_pk_top : float,
                 guard_time_factor : float = 1.7,
                 enable_pur : bool = True,
                 ):
        """
        Pile-up rejector module parameters computation. 

        Args:
            sampling_rate (float): Sampling rate of the ADC.
            shaper_s_tau_pk (float): Slow pulse shaper peaking time constant.
            shaper_s_tau_pk_top (float): Slow pulse shaper flat-top duration.
            shaper_f_tau_pk (float): Fast pulse shaper peaking time constant
            shaper_f_tau_pk_top (float): Fast pulse shaper flat-top duration.
            guard_time_factor (float, optional): Guard time factor. Defaults to 1.7.
            enable_pur (bool, optional): Enable module flag. Defaults to True.
        """
        
        super().__init__(sampling_rate = sampling_rate)

        self.shaper_s_tau_pk = shaper_s_tau_pk
        self.shaper_s_tau_pk_top = shaper_s_tau_pk_top
        self.shaper_f_tau_pk = shaper_f_tau_pk
        self.shaper_f_tau_pk_top = shaper_f_tau_pk_top
        self.guard_time_factor = guard_time_factor
        self.enable_flag = self.__validate_enable_flag(enable_pur)

        self.r1_preset_counter_32_0 = self._compute_r1_preset_counter()
        self.r2_enable_32_0 = self._compute_r2_enable()
        self.r3_delay_32_0 = self._compute_r3_delay()

        self.params_dict : dict = {
            'r1_preset_counter_32_0' : self.r1_preset_counter_32_0,
            'r2_enable_32_0'         : self.r2_enable_32_0,
            'r3_delay_32_0'          : self.r3_delay_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 3 parameters in the following order:
        - Preset counter
        - Enable
        - Delay
        """
        self.params_daq : list = [
            self.r1_preset_counter_32_0,
            self.r2_enable_32_0,
            self.r3_delay_32_0
        ]

    def _compute_r1_preset_counter(self) -> FixedPoint_Bin:
        """
        Computes the preset counter for the pileup rejector. Check the documentation
        for details on the computation.

        Returns:
            FixedPoint_Bin: Preset counter in Unsigned Q32.0 format
        """
        guard_time_f = self.guard_time_factor
        shp_s_tau_pk = self.shaper_s_tau_pk
        shp_s_tau_top = self.shaper_s_tau_pk_top
        t_clk = self.t_clk

        preset = int((guard_time_f * shp_s_tau_pk + shp_s_tau_top) / t_clk)
        preset = FixedPoint_Bin(preset, False, 32, 0)

        return preset
    
    def _compute_r2_enable(self) -> FixedPoint_Bin:
        """
        Computes the enable flag for the pileup rejector. Check the documentation
        for details on the computation.

        Returns:
            FixedPoint_Bin: Enable flag in Unsigned Q32.0 format
        """
        return self.enable_flag
    
    def _compute_r3_delay(self) -> FixedPoint_Bin:
        """
        Computes the delay for the pileup rejector. Check the documentation
        for details on the computation.

        Returns:
            FixedPoint_Bin: Delay in Unsigned Q32.0 format
        """
        shp_f_tau_pk = self.shaper_f_tau_pk
        shp_f_tau_top = self.shaper_f_tau_pk_top
        t_clk = self.t_clk

        delay = int((2*shp_f_tau_pk + shp_f_tau_top) / t_clk)
        delay = FixedPoint_Bin(delay, False, 32, 0)

        return delay    
    
    def __validate_enable_flag(self, flag : bool) -> bool:
        """
        Validates the enable flag format and returns it as an integer.

        Args:
            flag (bool): Enable flag

        Returns:
            int: The validated enable flag
        """
        return int(bool(flag))
    
    def __str__(self):
        return f"Pileup rejector: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()


class Dpp_High_Voltage:

    MAX_PMT_VOLTAGE = 1250
    DAC_RESOLUTION_BITS = 16
    def __init__(self,
                 set_hv : float):
        
        self.hv = set_hv
        self.r1_hv_32_0 = self._compute_r1_hv()

        self.params_dict : dict = {
            'r1_hv_32_0' : self.r1_hv_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the following parameter:
        - HV
        """
        self.params_daq : list = [
            self.r1_hv_32_0
        ]

    def _compute_r1_hv(self) -> FixedPoint_Bin:
        DAC_RES = self.DAC_RESOLUTION_BITS
        MAX_HV = self.MAX_PMT_VOLTAGE
        
        hv = float(self.hv)
        if hv > MAX_HV or hv < 0:
            raise ValueError(f"HV must be between 0 and {MAX_HV} volts.")
        
        hv = (hv*(2**DAC_RES)/MAX_HV) + 0.5

        return FixedPoint_Bin(hv, False, DAC_RES, 0)
    
    def __str__(self):
        return f"High voltage: {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()

class Dpp_Variable_Gain_Amplifier:

    #: Common fields across all board revisions, used to generically validate settings
    VALID_VERSIONS = ('A', 'B')
    GAIN_FINE_LIMITS = (1.0, 2.0)
    GAIN_COARSE_LIMITS = (0.5, 5.0)
    NAME_FIELD = 'NAME'
    DAC_RES_FIELD = 'DAC_RES'
    V_REF_FIELD = 'V_REF'
    
    #: Includes settings for board version/revision A only
    BOARD_A_DAC_SETTINGS = {
        NAME_FIELD : VALID_VERSIONS[0],
        DAC_RES_FIELD : 16,
        V_REF_FIELD : 3.3,
    }

    #: Includes settings for board version/revision B only
    BOARD_B_DAC_SETTINGS = {
        NAME_FIELD : VALID_VERSIONS[1],
        DAC_RES_FIELD : 12,
        V_REF_FIELD : 2.5,
    }

    #: Gathers the settings for each board revision
    BOARDS_SETTINGS = [
        BOARD_A_DAC_SETTINGS,
        BOARD_B_DAC_SETTINGS
    ]
    
    def __init__(self,
                 board_version : str = 'B',
                 gain_fine : float = 1.0,
                 gain_coarse : float = 1.0
                 ):
        """
        Variable-gain amplifier setup.
        The board revision/version defines the gain computation formula.
        Revision A uses the AD5693 DAC, while revision B uses the AD5697 DAC.

        Check documentation for further details.

        Args:
            board_version (str, optional): Board revision/version. Can be 'A' or 'B'. Defaults to 'B'.
            gain_fine (float, optional): Fine gain of the VGA. Expected between 1.0 and 2.0. Defaults to 1.0.
            gain_coarse (float, optional): Coarse gain of the VGA. Expected between 0.5 and 5.0. Defaults to 1.0.
        """

        self.version = self.__validate_version(board_version)
        self.gain_fine = self.__validate_gain_fine(gain_fine) 
        self.gain_coarse = self.__validate_gain_coarse(gain_coarse)

        self.r1_gain_fine_32_0 = self._compute_r1_gain_fine()
        self.r2_gain_coarse_32_0 = self._compute_r2_gain_coarse()

        self.params_dict : dict = {
            'r1_gain_fine_32_0' : self.r1_gain_fine_32_0,
            'r2_gain_coarse_32_0' : self.r2_gain_coarse_32_0
        }

        """
        ## Parameters sent to DAQ, see documentation in `doc` folder.
        ## The DAQ CLI expects the 2 parameters in the following order:
        - Gain_fine
        - Gain_coarse
        """
        self.params_daq : list = [
            self.r1_gain_fine_32_0,
            self.r2_gain_coarse_32_0
        ]

    def _compute_r1_gain_fine(self) -> FixedPoint_Bin:
        """
        Computes the DAC value to set the fine gain of the VGA. The output
        is dependent on the board revision/version.

        Returns:
            FixedPoint_Bin: DAC value
        """
        
        board_settings = self.__lookup_board_settings(self.version)

        gain_fine = self.__compute_gain_dac(
            gain = self.gain_fine,
            dac_resolution = board_settings[self.DAC_RES_FIELD],
            ref_voltage = board_settings[self.V_REF_FIELD]
        )

        return FixedPoint_Bin(gain_fine, False, 32, 0)
    
    def _compute_r2_gain_coarse(self) -> FixedPoint_Bin:
        """
        Computes the DAC value to set the coarse gain of the VGA. The output
        is dependent on the board revision/version.

        Returns:
            FixedPoint_Bin: DAC value
        """
        
        board_settings = self.__lookup_board_settings(self.version)

        gain_coarse = self.__compute_gain_dac(
            gain = self.gain_coarse,
            dac_resolution = board_settings[self.DAC_RES_FIELD],
            ref_voltage = board_settings[self.V_REF_FIELD]
        )

        return FixedPoint_Bin(gain_coarse, False, 32, 0)


    def __compute_gain_dac(self,
                        gain : float,
                        dac_resolution : int,
                        ref_voltage : float,
                        ) -> int:
        """
        Generic method to compute the DAC value for the given gain. Can
        be resused among the different board revisions.

        Args:
            gain (float): Gain value
            dac_resolution (int): DAC resolution
            ref_voltage (float): Reference voltage

        Returns:
            int: DAC value
        """

        OFFSET = 0.5 ## Quantization offset

        y = gain*(2**dac_resolution)/(2*ref_voltage) + OFFSET
        y = int(y)

        return y
    
    def __lookup_board_settings(self, name : str) -> dict:
        """
        Look up the settings for a given board revision/version.

        Args:
            name (str): Board revision/version. Can be 'A' or 'B'.

        Returns:
            dict: Settings for the given board revision/version

        Raises:
            ValueError: If the board revision/version is not found
        """
        for setting in self.BOARDS_SETTINGS:
            if setting[self.NAME_FIELD] == name:
                return setting
            
        raise ValueError(f"VGA Board revision {name} not found. Valid revisions are: {self.VALID_VERSIONS}.")


    def __validate_version(self, version : str) -> str:
        """
        Validates the version of the board.

        Args:
            version (str): Board revision/version. Can be 'A' or 'B'.

        Returns:
            str: Validated board revision/version

        Raises:
            ValueError: If the board revision/version is not valid
        """
        version = str(version).upper()

        if version not in self.VALID_VERSIONS:
            raise ValueError(f"VGA Board version must be one of the following: {self.VALID_VERSIONS}.")
        
        return version
    
    def __validate_gain_fine(self, gain_fine : float) -> float:
        """
        Validates the fine gain setting to be within the expected range.

        Args:
            gain_fine (float): Gain fine

        Returns:
            float: Validated gain fine

        Raises:
            ValueError: If the fine gain is not within the expected range
        """
        min_gain = self.GAIN_FINE_LIMITS[0]
        max_gain = self.GAIN_FINE_LIMITS[1]

        if gain_fine < min_gain or gain_fine > max_gain:
            raise ValueError(f"VGA fine gain must be between {min_gain} and {max_gain}.")
        
        return gain_fine
    
    def __validate_gain_coarse(self, gain_coarse : float) -> float:
        """
        Validates the coarse gain setting to be within the expected range.

        Args:
            gain_coarse (float): Gain coarse

        Returns:
            float: Validated coarse gain 

        Raises:
            ValueError: If the coarse gain is not within the expected range
        """
        min_gain = self.GAIN_COARSE_LIMITS[0]
        max_gain = self.GAIN_COARSE_LIMITS[1]

        if gain_coarse < min_gain or gain_coarse > max_gain:
            raise ValueError(f"VGA coarse gain must be between {min_gain} and {max_gain}.")
        
        return gain_coarse
    
    def __str__(self):
        return f"Variable-gain amplifier (VGA): {self.params_dict}"
    
    def __repr__(self):
        return self.__str__()
        

class Dpp_Parameters:
    def __init__(self, sampling_rate : float,
                 tau_d : float,
                 tau_r : float,
                 shaper_s_tau_pk : float,
                 shaper_s_tau_pk_top : float,
                 shaper_f_tau_pk : float,
                 shaper_f_tau_pk_top : float,
                 shaper_s_gain : float = 2.0,
                 shaper_f_gain : float = 2.0,
                 blr_s_threshold_high : float = 0.0,
                 blr_s_threshold_low : float = -0.05,
                 blr_s_threshold_gain : float = 2.0,
                 blr_s_threshold_low_gain : float = 2.0,
                 blr_f_threshold_high : float = 0.0,
                 blr_f_threshold_low : float = -0.05,
                 blr_f_threshold_gain : float = 1.5,
                 blr_f_threshold_low_gain : float = 6.0,
                 pkd_blanking_time_factor = 0.9,
                 pkd_time_over_threshold_factor = 0.44,
                 pur_guard_time_factor=1.7,
                 pur_enable=True,
                 pkd_s_x_min = 0.01,
                 pkd_s_x_max = 1.99,
                 pkd_f_x_min = 0.003,
                 pkd_f_x_max = 1.957,
                 invert_pulse : bool = False,
                 smoothing_factor : int = 1,
                 dc_offset : float = -0.77,
                 poles : int = 2,
                 tau_l : float = 50e-6,
                 scope_bram_size : int = 2048,
                 scope_threshold : float = 0.04,
                 scope_delay : int = 1000,
                 scope_enabled : bool = True,
                 scope_clear : bool = True,
                 scope_downsample : int = 1,
                 scope_sampling_mode_flag : int = 1,
                 scope_mux_ch1 : int = 0,
                 scope_mux_ch2 : int = 0,
                 timers_preset : int = 10000000,
                 timers_auto_mode : bool = False,
                 timers_a_live_time : bool = True,
                 timers_b_live_time : bool = False,
                 timers_c_live_time : bool = False,
                 timers_a_enable : bool = True,
                 timers_b_enable : bool = False,
                 timers_c_enable : bool = True,
                 timers_a_clear : bool = False,
                 timers_b_clear : bool = False,
                 timers_c_clear : bool = False,
                 high_voltage : float = 0.0,
                 vga_board_version : str = 'B',
                 vga_gain_fine : float = 1.0,
                 vga_gain_coarse : float = 1.0):
        """
        Parameters computation for DPP. Integrates individual modules: such as
        the pulse shaper, slow baseline restorer, slow peak detector, fast
        baseline restorer, and fast peak detector.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_d (float): Decay time constant of the detector (in seconds)
            tau_r (float): Rise time constant of the detector (in seconds)
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            tau_pk_fast (float): Peaking time for fast shaper (in seconds)
            tau_pk_top_fast (float): Flat top time for fast shaper (in seconds)
            threshold_gain (float, optional): Gain for high threshold. Defaults to 2.0.
            threshold_gain_fast (float, optional): Gain for high threshold for fast peak detector. Defaults to 1.5.
            threshold_low_gain (float, optional): Gain for low threshold. Defaults to 2.0.
            blanking_time_factor (float, optional): Blanking time factor. Defaults to 0.9.
            time_over_threshold_factor (float, optional): Time over threshold factor. Defaults to 0.44.
            x_min (float, optional): Minimum value for the output. Defaults to 0.01.
            x_max (float, optional): Maximum value for the output. Defaults to 1.99.
            invert_pulse (bool, optional): Invert original pulse before shaping. Defaults to False.
            dc_offset (float, optional): Signal input DC offset. Defaults to -0.77.
            poles (int, optional): Number of poles in the pulse shaper filter. Defaults to 2.
            tau_l (float, optional): Long undershoot constant (in seconds, for PMT only). Defaults to 50e-6.
        """
        self.shaper_slow = Dpp_Shaper(
            sampling_rate=sampling_rate,
            tau_d=tau_d,
            tau_r=tau_r,
            tau_l=tau_l,
            tau_pk=shaper_s_tau_pk,
            tau_pk_top=shaper_s_tau_pk_top,
            poles=poles,
            gain=shaper_s_gain,
        )

        self.blr_slow = Dpp_Blr_Slow(
            sampling_rate=sampling_rate,
            tau_pk=shaper_s_tau_pk,
            tau_pk_top=shaper_s_tau_pk_top,
            threshold_low=blr_s_threshold_low,
            threshold_high=blr_s_threshold_high,
            threshold_gain=blr_s_threshold_gain,
            threshold_low_gain=blr_s_threshold_low_gain
        )

        self.scope = Dpp_Scope(
            sampling_rate=sampling_rate,
            bram_size=scope_bram_size,
            threshold=scope_threshold,
            delay=scope_delay,
            enable=scope_enabled,
            clear=scope_clear,
            downsample_factor=scope_downsample,
            sampling_mode=scope_sampling_mode_flag
        )

        self.scope_mux = Dpp_Scope_Mux(
            ch1=scope_mux_ch1,
            ch2=scope_mux_ch2
        )

        self.timers = Dpp_Timers(
            tmr_preset_time=timers_preset,
            tmr_auto_mode=timers_auto_mode,
            tmr_a_lt=timers_a_live_time,
            tmr_b_lt=timers_b_live_time,
            tmr_c_lt=timers_c_live_time,
            tmr_a_en=timers_a_enable,
            tmr_b_en=timers_b_enable,
            tmr_c_en=timers_c_enable,
            tmr_a_clr=timers_a_clear,
            tmr_b_clr=timers_b_clear,
            tmr_c_clr=timers_c_clear
        )

        self.pk_detector_slow = Dpp_Pk_Detector_Slow(
            sampling_rate=sampling_rate,
            tau_pk=shaper_s_tau_pk,
            tau_pk_top=shaper_s_tau_pk_top,
            blanking_time_factor=pkd_blanking_time_factor,
            time_over_thrshld_factor=pkd_time_over_threshold_factor,
            x_min=pkd_s_x_min,
            x_max=pkd_s_x_max
        )

        self.formatter = Dpp_Formatter(
            sampling_rate=sampling_rate,
            dc_offset=dc_offset,
            invert_polarity=invert_pulse,
            smoothing_factor=smoothing_factor
        )

        self.shaper_fast = Dpp_Shaper(
            sampling_rate=sampling_rate,
            tau_d=tau_d,
            tau_r=tau_r,
            tau_l=tau_l,
            tau_pk=shaper_f_tau_pk,
            tau_pk_top=shaper_f_tau_pk_top,
            poles=poles,
            gain=shaper_f_gain,
        )

        self.blr_fast = Dpp_Blr_Fast(
            sampling_rate=sampling_rate,
            tau_pk=shaper_f_tau_pk,
            tau_pk_top=shaper_f_tau_pk_top,
            threshold_low=blr_f_threshold_low,
            threshold_high=blr_f_threshold_high,
            threshold_gain=blr_f_threshold_gain,
            threshold_low_gain=blr_f_threshold_low_gain
        )

        self.pk_detector_fast = Dpp_Pk_Detector_Fast(
            sampling_rate=sampling_rate,
            tau_pk=shaper_f_tau_pk,
            tau_pk_top=shaper_f_tau_pk_top,
            blanking_time_factor=pkd_blanking_time_factor,
            time_over_thrshld_factor=pkd_time_over_threshold_factor,
            x_min=pkd_f_x_min,
            x_max=pkd_f_x_max
        )

        self.pileup_rejector = Dpp_Pileup_Rejector(
            sampling_rate=sampling_rate,
            shaper_s_tau_pk=shaper_s_tau_pk,
            shaper_s_tau_pk_top=shaper_s_tau_pk_top,
            shaper_f_tau_pk=shaper_f_tau_pk,
            shaper_f_tau_pk_top=shaper_f_tau_pk_top,
            guard_time_factor=pur_guard_time_factor,
            enable_pur=pur_enable
        )

        self.high_voltage = Dpp_High_Voltage(
            set_hv=high_voltage
        )

        self.variable_gain_amplifier = Dpp_Variable_Gain_Amplifier(
            board_version=vga_board_version,
            gain_fine=vga_gain_fine,
            gain_coarse=vga_gain_coarse
        )
    
    def get_shaper_slow_params(self) -> dict:
        """
        Returns the parameters of the shaper filter as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the shaper filter.
        """
        return self.shaper_slow.params_dict

    def get_shaper_slow_params_daq(self) -> list:
        """
        Returns the slow shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface
        """
        return self.shaper_slow.params_daq
    

    def get_pk_detector_slow_params(self) -> dict:
        """
        Returns the parameters of the slow peak detector module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the slow peak detector module.
        """
        return self.pk_detector_slow.params_dict
    
    def get_pk_detector_slow_params_daq(self) -> list:
        """
        Returns the slow peak detector parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.pk_detector_slow.params_daq
    
    def get_scope_params(self) -> dict:
        """
        Returns the parameters of the scope module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the scope module.
        """
        return self.scope.params_dict
    
    def get_scope_params_daq(self) -> list:
        """
        Returns the slow peak detector parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        
        return self.scope.params_daq
    
    def get_timers_params(self) -> dict:
        """
        Returns the parameters of the timers module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the timers module.
        """
        return self.timers.params_dict
    
    def get_timers_params_daq(self) -> list:
        """
        Returns the slow peak detector parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.timers.params_daq

    
    def get_blr_slow_params(self) -> dict:
        """
        Returns the parameters of the slow base line restorer (BLR) module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the slow BLR module.
        """
        return self.blr_slow.params_dict
    
    def get_blr_slow_params_daq(self) -> list:
        """
        Returns the slow BLR parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.blr_slow.params_daq
    
    def get_scope_mux_params(self) -> dict:
        """
        Returns the parameters of the scope mux module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the scope mux module.
        """
        return self.scope_mux.params_dict
    
    def get_scope_mux_params_daq(self) -> list:
        """
        Returns the scope mux parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.scope_mux.params_daq
    
    def get_formatter_params(self) -> dict:
        """
        Returns the parameters of the formatter module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the formatter module.
        """
        return self.formatter.params_dict
    
    def get_formatter_params_daq(self) -> list:
        """
        Returns the formatter parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.formatter.params_daq

    def get_shaper_fast_params(self) -> dict:
        """
        Returns the parameters of the fast pulse shaper filter as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast pulse shaper filter.
        """
        return self.shaper_fast.params_dict
    
    def get_shaper_fast_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.shaper_fast.params_daq
    
    def get_blr_fast_params(self) -> dict:
        """
        Returns the parameters of the fast base line restorer (BLR) module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast BLR module.
        """
        return self.blr_fast.params_dict
    
    def get_blr_fast_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.blr_fast.params_daq
    
    def get_pk_detector_fast_params(self) -> dict:
        """
        Returns the parameters of the fast peak detector module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast peak detector module.
        """
        return self.pk_detector_fast.params_dict
    
    def get_pk_detector_fast_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.pk_detector_fast.params_daq
    
    def get_pileup_rejector_params(self) -> dict:
        """
        Returns the parameters of the pileup rejector module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the pileup rejector module.
        """
        return self.pileup_rejector.params_dict
    
    def get_pileup_rejector_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.pileup_rejector.params_daq

    def get_high_voltage_params(self) -> dict:
        """
        Returns the parameters of the high voltage for PMT module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the high voltage module.
        """
        return self.high_voltage.params_dict
    
    def get_high_voltage_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.high_voltage.params_daq
    
    def get_vga_params(self) -> dict:
        """
        Returns the parameters for the variable-gain amplifier module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the VGA module.
        """
        return self.variable_gain_amplifier.params_dict
    
    def get_vga_params_daq(self) -> list:
        """
        Returns the fast shaper parameter list ready to be streamed
        out to the DAQ/MCA using the serial command line interface

        Returns:
            list: A serializable list of parameters to configure the MCA/DAQ
        """
        return self.variable_gain_amplifier.params_daq
        

"""
Usecase example of the DPP parameters computation, set with default values for a NaI(Tl) SiPM detector
"""
if __name__ == '__main__':
    # Set the following values according to your detector and DPP settings
    SAMPLING_RATE = 50e6 #: ADC sampling rate (in Hz)
    TAU_D = 1.145e-6  #: Detector decay time constant (in seconds)
    TAU_R = 0.220e-6  #: Detector rise time constant (in seconds)
    TAU_L = 50e-6   #: PMT-only! Long decay constant (in seconds)
    SHAPER_S_TAU_PK = 3.0e-6 #: Pulse shaper (slow) peaking time (in seconds)
    SHAPER_S_TAU_PK_TOP = 0.0e-6 #: Pulse shaper (slow) flat-top (in seconds)
    SHAPER_F_TAU_PK = 0.2e-6 # : Pulse shaper (fast) peaking time (in seconds)
    SHAPER_F_TAU_PK_TOP = 0.0e-6 #: Pulse shaper (fast) flat-top (in seconds)
    POLES = 2   #: Number of poles in the pulse shaper filter (SiPM: 2, PMT: 3)
    SHAPER_S_GAIN = 1.0 #: Digital gain of the slow pulse shaper filter
    SHAPER_F_GAIN = 1.0 #: Digital gain of the fast pulse shaper filter
    DC_OFFSET = -0.77 #: ADC input signal DC offset (in Volts)
    INVERT_PULSE = False #: Is the original pulse inverted before shaping?
    SMOOTHING_FACTOR = 2 # Moving averaging Formatter flags (1, 2, 4, or 8)
    BLR_S_THRESHOLD_HIGH = 0.00 #: BLR slow clamping threshold high (in Volts)
    BLR_S_THRESHOLD_LOW = -0.05 #: BLR slow campling threshold low (in Volts)
    BLR_S_THRESHOLD_GAIN = 3.0 #: Coarse gain of the slow baseline restorer
    BLR_S_THRESHOLD_LOW_GAIN = 50 #: Fine gain of the slow baseline restorer
    BLR_F_THRESHOLD_HIGH = 0.00 #: BLR fast clamping threshold high (in Volts)
    BLR_F_THRESHOLD_LOW = -0.05 #: BLR fast campling threshold low (in Volts)
    BLR_F_THRESHOLD_GAIN = 6.0 #: Coarse gain of the fast baseline restorer
    BLR_F_THRESHOLD_LOW_GAIN = 2.0 #: Fine gain of the fast baseline restorer
    PKD_BLANKING_TIME_FACTOR = 0.9 #: Peak detector blanking time factor
    PKD_TIME_OVER_THRESHOLD_FACTOR = 0.44 #: Peak detector time-over-threshold factor
    PUR_GUARD_TIME_FACTOR = 1.7 #: Pileup rejector guard time factor
    PUR_ENABLE = True #: Enable the pileup rejector module
    PKD_S_X_MIN = 0.01 #: Peak detector minimum value to be considered valid (in Volts)
    PKD_S_X_MAX = 1.99 #: Peak detector maximum value to be considered valid (in Volts)
    PKD_F_X_MIN = 0.003 #: Peak detector minimum value to be considered valid (in Volts)
    PKD_F_X_MAX = 1.957 #: Peak detector maximum value to be considered valid (in Volts)
    SCOPE_BRAM_SIZE = 2048 #: Size of the scope buffer (in samples)
    SCOPE_THRESHOLD = 0.048 #: Scope threshold (in Volts)
    SCOPE_DELAY = 1000 #: Scope delay (in samples)
    SCOPE_ENABLED = True #: Enable the scope module
    SCOPE_CLEAR = True #: Clear the scope buffer on startup
    SCOPE_DOWNSAMPLE_FACTOR = 0 #: Valid values: 1, 2, 3, 4
    SCOPE_SAMPLING_MODE_FLAG = 1 #: 0: Decimate, 1: Max between two samples, 2: Min between two samples
    SCOPE_MUX_CH1 = 0 #: Scope channel 1
    SCOPE_MUX_CH2 = 0 #: Scope channel 2
    TIMERS_PRESET = 10000000 #: Timer preset (collection time) in milliseconds,
    TIMERS_AUTO_MODE = False #: Automatic/manual mode acquisition
    TIMERS_A_LIVE_TIME = True #: Measure live time (LT) with Timer A
    TIMERS_B_LIVE_TIME = False #: Measure real time (RT) with Timer B
    TIMERS_C_LIVE_TIME = False #: Measure real time (RT) with Timer C
    TIMERS_A_ENABLE = True #: Enable Timer A
    TIMERS_B_ENABLE = False #: Enable Timer B
    TIMERS_C_ENABLE = True #: Enable Timer C
    TIMERS_A_CLEAR = False #: Reset timer A before starting
    TIMERS_B_CLEAR = False #: Reset timer B before starting
    TIMERS_C_CLEAR = False #: Reset timer C before starting
    HIGH_VOLTAGE = 0 #: High voltage for PMT (in Volts)
    VGA_VERSION = 'B' #: Version/revision of the board. Valid values: A, B (string)
    VGA_GAIN_FINE = 1.0 #: Fine gain of the variable-gain amplifier in the AFE (before ADC)
    VGA_GAIN_COARSE = 1.0 #: Coarse gain of the variable-gain amplifier in the AFE (before ADC)
    


    # Initializing the DPP parameters class instance
    dpp_parameters = Dpp_Parameters(
        sampling_rate=SAMPLING_RATE,
        tau_d=TAU_D,
        tau_r=TAU_R,
        shaper_s_tau_pk=SHAPER_S_TAU_PK,
        shaper_s_tau_pk_top=SHAPER_S_TAU_PK_TOP,
        shaper_f_tau_pk=SHAPER_F_TAU_PK,
        shaper_f_tau_pk_top=SHAPER_F_TAU_PK_TOP,
        shaper_s_gain=SHAPER_S_GAIN,
        shaper_f_gain=SHAPER_F_GAIN,
        blr_s_threshold_high=BLR_S_THRESHOLD_HIGH,
        blr_s_threshold_low=BLR_S_THRESHOLD_LOW,
        blr_s_threshold_gain=BLR_S_THRESHOLD_GAIN,
        blr_s_threshold_low_gain=BLR_S_THRESHOLD_LOW_GAIN,
        blr_f_threshold_high=BLR_F_THRESHOLD_HIGH,
        blr_f_threshold_low=BLR_F_THRESHOLD_LOW,
        blr_f_threshold_gain=BLR_F_THRESHOLD_GAIN,
        blr_f_threshold_low_gain=BLR_F_THRESHOLD_LOW_GAIN,
        pkd_blanking_time_factor=PKD_BLANKING_TIME_FACTOR,
        pkd_time_over_threshold_factor=PKD_TIME_OVER_THRESHOLD_FACTOR,
        pur_guard_time_factor=PUR_GUARD_TIME_FACTOR,
        pur_enable=PUR_ENABLE,
        pkd_s_x_min=PKD_S_X_MIN,
        pkd_s_x_max=PKD_S_X_MAX,
        pkd_f_x_min=PKD_F_X_MIN,
        pkd_f_x_max=PKD_F_X_MAX,
        invert_pulse=INVERT_PULSE,
        smoothing_factor=SMOOTHING_FACTOR,
        dc_offset=DC_OFFSET,
        poles=POLES,
        tau_l=TAU_L,
        scope_bram_size=SCOPE_BRAM_SIZE,
        scope_threshold=SCOPE_THRESHOLD,
        scope_delay=SCOPE_DELAY,
        scope_enabled=SCOPE_ENABLED,
        scope_clear=SCOPE_CLEAR,
        scope_downsample=SCOPE_DOWNSAMPLE_FACTOR,
        scope_sampling_mode_flag=SCOPE_SAMPLING_MODE_FLAG,
        scope_mux_ch1=SCOPE_MUX_CH1,
        scope_mux_ch2=SCOPE_MUX_CH2,
        timers_preset=TIMERS_PRESET,
        timers_auto_mode=TIMERS_AUTO_MODE,
        timers_a_live_time=TIMERS_A_LIVE_TIME,
        timers_b_live_time=TIMERS_B_LIVE_TIME,
        timers_c_live_time=TIMERS_C_LIVE_TIME,
        timers_a_enable=TIMERS_A_ENABLE,
        timers_b_enable=TIMERS_B_ENABLE,
        timers_c_enable=TIMERS_C_ENABLE,
        timers_a_clear=TIMERS_A_CLEAR,
        timers_b_clear=TIMERS_B_CLEAR,
        timers_c_clear=TIMERS_C_CLEAR,
        high_voltage=HIGH_VOLTAGE,
        vga_board_version=VGA_VERSION,
        vga_gain_fine=VGA_GAIN_FINE,
        vga_gain_coarse=VGA_GAIN_COARSE
    )

    # You can either print the class instance to show its parameters in console
    print("\n\nDPP parameters (printable version):")
    print(dpp_parameters.shaper_slow)
    print(dpp_parameters.pk_detector_slow)
    print(dpp_parameters.scope)
    print(dpp_parameters.timers)
    print(dpp_parameters.blr_slow)
    print(dpp_parameters.scope_mux)
    print(dpp_parameters.formatter)
    print(dpp_parameters.shaper_fast)
    print(dpp_parameters.blr_fast)
    print(dpp_parameters.pk_detector_fast)
    print(dpp_parameters.pileup_rejector)
    print(dpp_parameters.high_voltage)
    print(dpp_parameters.variable_gain_amplifier)
    
    # Or explicitly call the corresponding methods `get_***_params()` to retrieve the parameters into variables
    print("\nDPP parameters (callable version):")
    print(f"Pulse shaper slow: {dpp_parameters.get_shaper_slow_params()}")
    print(f"Peak detector slow:{dpp_parameters.get_pk_detector_slow_params()}")
    print(f"Scope: {dpp_parameters.get_scope_params()}")
    print(f"Timers: {dpp_parameters.get_timers_params()}")
    print(f"BLR slow: {dpp_parameters.get_blr_slow_params()}")
    print(f"Scope mux: {dpp_parameters.get_scope_mux_params()}")
    print(f"Formatter: {dpp_parameters.get_formatter_params()}")
    print(f"Pulse shaper fast: {dpp_parameters.get_shaper_fast_params()}")
    print(f"BLR fast: {dpp_parameters.get_blr_fast_params()}")
    print(f"Peak detector fast: {dpp_parameters.get_pk_detector_fast_params()}")
    print(f"Pileup rejector: {dpp_parameters.get_pileup_rejector_params()}")
    print(f"High voltage: {dpp_parameters.get_high_voltage_params()}")
    print(f"Variable gain amplifier: {dpp_parameters.get_vga_params()}")

    # Also the parameters sent to the DAQ/MCA through the serial interface can be listed as follows.
    print("\nDPP parameter values streamable to the DAQ/MCA using CLI:")
    print(f"Pulse shaper slow: {dpp_parameters.get_shaper_slow_params_daq()}")
    print(f"Peak detector slow:{dpp_parameters.get_pk_detector_slow_params_daq()}")
    print(f"Scope: {dpp_parameters.get_scope_params_daq()}")
    print(f"Timers: {dpp_parameters.get_timers_params_daq()}")
    print(f"BLR slow: {dpp_parameters.get_blr_slow_params_daq()}")
    print(f"Scope mux: {dpp_parameters.get_scope_mux_params_daq()}")
    print(f"Formatter: {dpp_parameters.get_formatter_params_daq()}")
    print(f"Pulse shaper fast: {dpp_parameters.get_shaper_fast_params_daq()}")
    print(f"BLR fast: {dpp_parameters.get_blr_fast_params_daq()}")
    print(f"Peak detector fast: {dpp_parameters.get_pk_detector_fast_params_daq()}")
    print(f"Pileup rejector: {dpp_parameters.get_pileup_rejector_params_daq()}")
    print(f"High voltage: {dpp_parameters.get_high_voltage_params_daq()}")
    print(f"Variable gain amplifier: {dpp_parameters.get_vga_params_daq()}")
