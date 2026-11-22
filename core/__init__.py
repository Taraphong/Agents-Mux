"""Pure, Flask-free building blocks shared by the application.

Modules in this package never import ``app``: app.py imports from them, so the
application object stays the single assembly point.
"""
