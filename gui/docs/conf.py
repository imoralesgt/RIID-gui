"""Sphinx configuration for the RIID GUI documentation."""

import os
import sys

sys.path.insert(0, os.path.abspath('..'))

project = 'RIID GUI'
copyright = '2026, Nuclear Science and Instrumentation Laboratory (NSIL), IAEA'
author = 'NSIL, IAEA'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

napoleon_google_docstring = True
napoleon_numpy_docstring = False

autodoc_member_order = 'bysource'
autodoc_default_options = {
    'members': True,
    'undoc-members': False,
    'show-inheritance': True,
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'furo'
html_static_path = ['_static']
html_title = 'RIID GUI Documentation'
