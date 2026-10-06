"""Build a read-only version of the current station placement preflight."""
from pathlib import Path

source = Path(__file__).with_name('place_station_clusters.py')
out = Path(__file__).with_name('probe_station_clusters.py')
code = source.read_text(encoding='utf-8').split('# All support probes completed before the first write;')[0]
code = code.replace("    assert math.degrees(math.acos(n[2]))<=12., label+' needs a gentler measured patch'\n", '')
code = code.replace("    assert max(support)-min(support)<=2.5, label+' needs a more planar measured patch; no sunken/floating correction applied'\n", '')
code += "\nprint('STATION_PLANS',json.dumps([{'label':p['label'],'clearance':p['corner_clearance_cm'],'support':p['support_cm']} for p in plans],separators=(',',':')))\n"
out.write_text(code, encoding='utf-8')
print(out)
