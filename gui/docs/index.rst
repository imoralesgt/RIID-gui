RIID GUI documentation
=======================

Backend and frontend reference for the RIID station's NiceGUI web application.
See the `repository README <https://github.com/imoralesgt/RIID-gui#readme>`_
for how to install and run the GUI, and a tour of its features from an
operator's perspective. This site documents the source itself, module by
module.

.. toctree::
   :maxdepth: 2
   :caption: Application entry point

   modules/main
   modules/config

.. toctree::
   :maxdepth: 2
   :caption: Backend

   modules/riid_service
   modules/state_engine
   modules/ml_inference
   modules/ml_preprocessing

.. toctree::
   :maxdepth: 2
   :caption: Views (tabs)

   modules/view_spectrum_id
   modules/view_recording
   modules/view_download
   modules/view_calibration

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
