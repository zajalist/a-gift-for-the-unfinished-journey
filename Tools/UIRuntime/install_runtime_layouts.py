"""Prepare native Hayba UMG packets offline. Do not run in Unreal Python.

The root editor operator installs specs with ui_create_widget, ui_build_tree,
ui_set_widget_properties, ui_compile_widget, ui_save_widget and ui_query.
Direct Python access to Blueprint.WidgetTree and WidgetTree.RootWidget is
protected in UE 5.8 and is deliberately not used by this packet.
"""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().with_name("generate_hayba_packets.py")), run_name="__main__")
