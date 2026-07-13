import ai_edge_litert.interpreter as tflite
import numpy as np
import os
import time
import argparse
import sys
from ml_preprocessing import MLPreprocessing 
from sklearn.preprocessing import LabelEncoder
from config import logger

le = LabelEncoder()
le.fit(['bkg', 'co', 'coeu', 'cs', 'csco', 'cscoeu', 'cseu', 'eu', 'u'])

def inference(spectrum_data : list,
            spectrum_live_time : list,
            bkgnd_data : list = [],
            bkgnd_live_time : int = 0):
    pass