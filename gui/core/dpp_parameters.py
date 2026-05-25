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
__version__ = "1.0"
__date__ = "2025-10-03"

from fixedpoint import FixedPoint
import numpy as np

class FixedPoint_Bin:
    def __new__(cls, val : int, signed : bool, m : int, n : int, return_binary_str : bool = False, *args, **kwargs):
        """Constructor of a FixedPoint object, further padded with leading zeros
        and returned in binary format. 
        
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

class __Dpp_Common:

    def __init__(self, sampling_rate : float):
        """
        Shared parameters among DPP modules.

        Args:
            sampling_rate (float): Sampling rate of the signal (Hz)
        """
        self.sampling_rate = sampling_rate
        self.t_clk = 1.0/sampling_rate

    def _compute_na(self, tau_pk : float):
        return np.ceil(tau_pk/self.t_clk)
    
    def _compute_nb(self, tau_pk : float, tau_pk_top : float):
        return np.ceil((tau_pk+tau_pk_top)/self.t_clk)

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
                dc_offset : float = 0.0,
                invert_pulse : bool = False,
                dc_offset_at_filter_input : float = 0.0,
                dc_offset_at_filter_output : float = 0.0,):
        """
        Pulse shaper parameters computation.

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
        self.dc_offset = dc_offset #: Signal input DC offset
        self.invert_pulse = invert_pulse #: Invert original pulse before shaping
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
                threshold_gain : float = 2.0,
                threshold_low_gain : float = 2.0,
                ):
        """
        Baseline restorer parameters computation. Slow BLR module used in MCA.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            threshold_gain (float, optional): Gain for high threshold. Defaults to 2.0.
            threshold_low_gain (float, optional): Gain for low threshold. Defaults to 2.0.
        """
        super().__init__(sampling_rate = sampling_rate)
        self.threshold_gain = threshold_gain
        self.threshold_low_gain = threshold_low_gain
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
        
    def _compute_r1_threshold(self):
        # Threshold clamping value must be negative
        thr_lo = -0.05
        thr_lo_bits = FixedPoint_Bin(thr_lo, True, 2, 14)

        # Threshold offset value must ve positive (or at least 0)
        thr_hi = 0.0
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
        m = 1
        ## bit_0 = 1 blr is disabled and correction is 0 (blr not used, accumulator is in reset state)
        ## bit_0 = 0 blr is enabled
        ## bit_1,2 = m
        flags = m << 1

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
        event energy for the MCA.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            blanking_time_factor (float, optional): Blanking time factor. Defaults to 0.9.
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
    

class Dpp_Blr_Fast(__Dpp_Common):

    TAU_BLR_CHARGE = 1e-3 # 1 ms
    TAU_BLR_DISCHARGE = 50e-3 # 50 ms
    
    def __init__(self, 
                sampling_rate : float,
                tau_pk : float,
                tau_pk_top: float,
                threshold_gain : float = 1.5,
                threshold_low_gain : float = 2.0,
                ):
        """
        Fast BLR module parameters computation. Used in pile-up rejection module.

        Args:
            sampling_rate (float): Sampling rate of the ADC
            tau_pk (float): Peaking time (in seconds)
            tau_pk_top (float): Flat top time (in seconds)
            threshold_gain (float, optional): Gain for high threshold. Defaults to 1.5.
            threshold_low_gain (float, optional): Gain for low threshold. Defaults to 2.0.
        """
        super().__init__(sampling_rate = sampling_rate)
        self.threshold_gain = threshold_gain
        self.threshold_low_gain = threshold_low_gain
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

    def _compute_r1_threshold(self):
        # Threshold clamping value must be negative
        thr_lo = -0.100
        thr_lo_bits = FixedPoint_Bin(thr_lo, True, 2, 14)

        # Threshold offset value must ve positive (or at least 0)
        thr_hi = 0.0
        thr_hi_bits = FixedPoint_Bin(thr_hi, True, 2, 14)

        return (thr_hi_bits<<16 | thr_lo_bits)
    
    def _compute_r2_flags(self):
        ## define bits bit_1_2: 'm' 
        ## m defines blr speed, how fast baseline goes to zero exp(-n*Tclk/tau_blr)
        ## default value is m=3
        ## m = 3 tau_blr = 1.31 msec @ Tclk=20e-9 = 50MHz, 1/2^16
        ## m = 2 tau_blr = 81.9 usec @ Tclk=20e-9 = 50MHz, 1/2^12
        ## m = 1 tau_blr = 10.2 usec @ Tclk=20e-9 = 50MHz, 1/2^9   
        ## m = 0 tau_blr = 1.28 usec @ Tclk=20e-9 = 50MHz, 1/2^6 
        m = 2
        ## bit_0 = 1 blr is disabled and correction is 0 (blr not used, accumulator is in reset state)
        ## bit_0 = 0 blr is enabled
        ## bit_1,2 = m
        flags = m << 1

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
        Fast peak detector parameters computation. Used in pile-up rejection module.

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
        
        self.params_dict = {
            'r1_blanking_time_32_0'         : self.r1_blanking_time_32_0,
            'r2_time_over_threshold_32_0'   : self.r2_time_over_threshold_32_0,
            'r3_x_min_32_0'                 : self.r3_x_min_32_0,
            'r4_x_max_32_0'                 : self.r4_x_max_32_0,
            'r5_flags_32_0'                 : self.r5_flags_32_0
        }
    def __str__(self):
        return f"Peak detector fast: {self.params_dict}"

    def __repr__(self):
        return self.__str__()
        

class Dpp_Parameters:
    def __init__(self, sampling_rate : float,
                 tau_d : float,
                 tau_r : float,
                 tau_pk : float,
                 tau_pk_top : float,
                 tau_pk_fast : float,
                 tau_pk_top_fast : float,
                 shaper_slow_gain : float = 2.0,
                 shaper_fast_gain : float = 2.0,
                 threshold_gain : float = 2.0,
                 threshold_gain_fast : float = 1.5,
                 threshold_low_gain : float = 2.0,
                 blanking_time_factor = 0.9,
                 time_over_threshold_factor = 0.44,
                 x_min = 0.01,
                 x_max = 1.99,
                 invert_pulse : bool = False,
                 dc_offset : float = -0.77,
                 poles : int = 2,
                 tau_l : float = 50e-6):
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
            tau_pk=tau_pk,
            tau_pk_top=tau_pk_top,
            poles=poles,
            gain=shaper_slow_gain,
            dc_offset=dc_offset,
            invert_pulse=invert_pulse,
        )

        self.blr_slow = Dpp_Blr_Slow(
            sampling_rate=sampling_rate,
            tau_pk=tau_pk,
            tau_pk_top=tau_pk_top,
            threshold_gain=threshold_gain,
            threshold_low_gain=threshold_low_gain
        )

        self.pk_detector_slow = Dpp_Pk_Detector_Slow(
            sampling_rate=sampling_rate,
            tau_pk=tau_pk,
            tau_pk_top=tau_pk_top,
            blanking_time_factor=blanking_time_factor,
            time_over_thrshld_factor=time_over_threshold_factor,
            x_min=x_min,
            x_max=x_max
        )

        self.shaper_fast = Dpp_Shaper(
            sampling_rate=sampling_rate,
            tau_d=tau_d,
            tau_r=tau_r,
            tau_l=tau_l,
            tau_pk=tau_pk_fast,
            tau_pk_top=tau_pk_top_fast,
            poles=poles,
            gain=shaper_fast_gain,
            dc_offset=dc_offset,
            invert_pulse=invert_pulse,
        )

        self.blr_fast = Dpp_Blr_Fast(
            sampling_rate=sampling_rate,
            tau_pk=tau_pk,
            tau_pk_top=tau_pk_top_fast,
            threshold_gain=threshold_gain_fast,
            threshold_low_gain=threshold_low_gain
        )

        self.pk_detector_fast = Dpp_Pk_Detector_Fast(
            sampling_rate=sampling_rate,
            tau_pk=tau_pk,
            tau_pk_top=tau_pk_top_fast,
            blanking_time_factor=blanking_time_factor,
            time_over_thrshld_factor=time_over_threshold_factor,
            x_min=x_min,
            x_max=x_max
        )
    
    def get_shaper_slow_params(self) -> dict:
        """
        Returns the parameters of the shaper filter as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the shaper filter.
        """
        return self.shaper_slow.params_dict
    
    def get_blr_slow_params(self) -> dict:
        """
        Returns the parameters of the slow base line restorer (BLR) module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the slow BLR module.
        """
        return self.blr_slow.params_dict
    
    def get_pk_detector_slow_params(self) -> dict:
        """
        Returns the parameters of the slow peak detector module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the slow peak detector module.
        """
        return self.pk_detector_slow.params_dict
    
    def get_shaper_fast_params(self) -> dict:
        """
        Returns the parameters of the fast pulse shaper filter as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast pulse shaper filter.
        """
        return self.shaper_fast.params_dict
    
    def get_blr_fast_params(self) -> dict:
        """
        Returns the parameters of the fast base line restorer (BLR) module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast BLR module.
        """
        return self.blr_fast.params_dict
    
    def get_pk_detector_fast_params(self) -> dict:
        """
        Returns the parameters of the fast peak detector module as a dictionary.

        Returns:
            dict: A dictionary containing the parameters of the fast peak detector module.
        """
        return self.pk_detector_fast.params_dict
        

"""
Usecase example of the DPP parameters computation, set with default values for a NaI(Tl) SiPM detector
"""
if __name__ == '__main__':
    # Set the following values according to your detector and DPP settings
    SAMPLING_RATE = 50e6 #: ADC sampling rate (in Hz)
    TAU_D = 0.2e-6  #: Detector decay time constant (in seconds)
    TAU_R = 1.145e-6  #: Detector rise time constant (in seconds)
    TAU_L = 50e-6   #: PMT-only! Long decay constant (in seconds)
    TAU_PK = 3.0e-6 #: Pulse shaper (slow) peaking time (in seconds)
    TAU_PK_TOP = 0.0e-6 #: Pulse shaper (slow) flat-top (in seconds)
    TAU_PK_FAST = 0.3e-6 # : Pulse shaper (fast) peaking time (in seconds)
    TAU_PK_TOP_FAST = 0.0e-6 #: Pulse shaper (fast) flat-top (in seconds)
    POLES = 2   #: Number of poles in the pulse shaper filter (SiPM: 2, PMT: 3)
    GAIN_SHAPER_SLOW = 2 #: Digital gain of the slow pulse shaper filter
    GAIN_SHAPER_FAST = 2 #: Digital gain of the fast pulse shaper filter
    DC_OFFSET = -0.88 #: ADC input signal DC offset (in Volts)
    INVERT_PULSE = True #: Is the original pulse inverted before shaping?
    THRESHOLD_GAIN = 2.0 #: Coarse gain of the slow baseline restorer
    THRESHOLD_LOW_GAIN = 2 #: Fine gain of the slow baseline restorer
    THRESHOLD_GAIN_FAST = 2 #: Coarse gain of the fast baseline restorer
    BLANKING_TIME_FACTOR = 0.9 #: Peak detector blanking time factor
    TIME_OVER_THRESHOLD_FACTOR = 0.44 #: Peak detector time-over-threshold factor
    X_MIN = 0.01 #: Peak detector minimum value to be considered valid (in Volts)
    X_MAX = 1.99 #: Peak detector maximum value to be considered valid (in Volts)

    # Initializing the DPP parameters class instance
    dpp_parameters = Dpp_Parameters(
        sampling_rate=SAMPLING_RATE,
        tau_d=TAU_D,
        tau_r=TAU_R,
        tau_pk=TAU_PK,
        tau_pk_top=TAU_PK_TOP,
        tau_pk_fast=TAU_PK_FAST,
        tau_pk_top_fast=TAU_PK_TOP_FAST,
        shaper_slow_gain=GAIN_SHAPER_SLOW,
        shaper_fast_gain=GAIN_SHAPER_FAST,
        threshold_gain=THRESHOLD_GAIN,
        threshold_gain_fast=THRESHOLD_GAIN_FAST,
        threshold_low_gain=THRESHOLD_LOW_GAIN,
        blanking_time_factor=BLANKING_TIME_FACTOR,
        time_over_threshold_factor=TIME_OVER_THRESHOLD_FACTOR,
        x_min=X_MIN,
        x_max=X_MAX,
        invert_pulse=INVERT_PULSE,
        dc_offset=DC_OFFSET,
        poles=POLES,
        tau_l=TAU_L,
    )

    # You can either print the class instance to show its parameters in console
    print("\n\nDPP parameters (printable version):")
    print(dpp_parameters.shaper_slow)
    print(dpp_parameters.blr_slow)
    print(dpp_parameters.pk_detector_slow)
    print(dpp_parameters.shaper_fast)
    print(dpp_parameters.blr_fast)
    print(dpp_parameters.pk_detector_fast)
    
    # Or explicitly call the corresponding methods `get_***_params()` to retrieve the parameters into variables
    print("\nDPP parameters (callable version):")
    print(f"Pulse shaper slow: {dpp_parameters.get_shaper_slow_params()}")
    print(f"BLR slow: {dpp_parameters.get_blr_slow_params()}")
    print(f"Peak detector slow:{dpp_parameters.get_pk_detector_slow_params()}")
    print(f"Pulse shaper fast: {dpp_parameters.get_shaper_fast_params()}")
    print(f"BLR fast: {dpp_parameters.get_blr_fast_params()}")
    print(f"Peak detector fast: {dpp_parameters.get_pk_detector_fast_params()}")
