"""Root-operated bounded observations of an existing PIE session; default is offline.

No input injection, start/restart, teleport, quality change or asset operation.
Screenshots are separate from timed CSV windows. See the companion runbook.
"""
from pathlib import Path
import argparse
import json
import math
import re
import time

import bounded_pie_profile as profile

ROOT = profile.ROOT
CASES = ('motor', 'repair', 'storm', 'body', 'settings')
START_REFUSED = re.compile(r'capture was already running|already a pending start command',re.I)
FAULT = re.compile(profile.FAULT.pattern + r'|EXCEPTION_ACCESS_VIOLATION|HCR-NATIVE|unknown opcode',re.I)
PLAN = """Root owns the editor and existing global lease (150s remaining).
Use one active PIE world, one CSV recorder, the same viewport/settings, and operator input.
snapshot --case motor --label ready --owner OWNER --editor-pid PID
window --case motor --label lesson --seconds 35 --owner OWNER --editor-pid PID
Observe one case at a time; no screenshot during its timed CSV window.
Cases: motor, repair, storm, body, settings. Labels record actual operator actions.
Success leaves PIE running; fault/timeout abort requests normal PIE stop.
See docs/performance/2026-10-01-gameplay-acceptance.md for acceptance criteria.
"""


class Bridge(profile.Bridge):
    def __init__(self, owner):
        self.next_rpc_at = 0.0
        super().__init__(owner)

    def call(self, command, params=None, timeout=5):
        # Avoid the native16-client cap while closed sockets age out for5s.
        delay = self.next_rpc_at - time.monotonic()
        if delay > 0: time.sleep(delay)
        self.next_rpc_at = time.monotonic() + .6
        value = super().call(command, params, timeout)
        if value.get('_truncated') or value.get('truncated'):
            raise RuntimeError('Truncated observation: ' + command)
        return value


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def context(args):
    bridge = Bridge(args.owner)
    live = bridge.call('editor_get_state')
    if not live.get('pie_running') or '/Game/level/Saskarta_WP' not in live.get('map', ''):
        raise RuntimeError('An existing Saskarta_WP PIE session is required')
    pc = bridge.actor('PC_Saskarta_C')  # requires exactly one PIE world
    if not pc: raise RuntimeError('No current local player controller')
    host = profile.host_sample(args.editor_pid)
    if host['available_ram_fraction'] < .15: raise RuntimeError('Available RAM is below15%')
    path = ROOT / 'Saved/Verification/gameplay_acceptance' / (
        time.strftime('%Y%m%d_%H%M%S') + '_' + args.case + '_' + args.label + '_' + args.mode)
    path.mkdir(parents=True, exist_ok=False)
    return bridge, pc, path


def snapshot(args):
    bridge, pc, out = context(args)
    requested = out / 'frame.png'
    result = bridge.call('editor_pie_screenshot', {'filename':str(requested), 'show_ui':True})
    save(out/'request.json', result)
    if result.get('pie_world_count') != 1 or result.get('ambiguous_target_warning'):
        raise RuntimeError('Screenshot target is ambiguous')
    if Path(result.get('filename', '')).resolve() != requested.resolve():
        raise RuntimeError('Screenshot returned a different filename')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = bridge.call('editor_pie_screenshot', {'filename':str(requested), 'check_only':True})
        save(out/'completion.json', result)
        if result.get('captured') is True:
            if not requested.is_file() or requested.stat().st_size == 0:
                raise RuntimeError('Capture reported complete without a nonempty file')
            print(json.dumps({'image':str(requested),'evidence':str(out),'status':'captured_not_visually_accepted'}))
            return 0
    raise RuntimeError('Screenshot did not finish within the bounded window')


def completed_csv(report, before):
    return profile.completed_csv(report, before)


def require_idle_csv(log_text):
    # UE5.8 CsvProfiler.cpp emits Starting, started+GUID, and Ended in this order.
    starts=list(re.finditer(r'LogCsvProfiler:.*Capture (?:Starting|started\. CSV ID:)',log_text))
    ends=list(re.finditer(r'LogCsvProfiler:.*Capture Ended\. Writing CSV to file',log_text))
    if starts and (not ends or starts[-1].start()>ends[-1].start()):
        raise RuntimeError('Log evidence shows an existing/pending CSV capture; finish it before this trial')
    return {'start_events':len(starts),'end_events':len(ends),'last_start_precedes_end':True}


def observe_csv(report, recent):
    if START_REFUSED.search(recent):
        report['csv_ownership']='refused_existing_capture'
        raise RuntimeError('CSV START refused because an existing/pending capture owns the recorder')
    for identity in profile.CSV_START.findall(recent):
        if report.get('csv_id') not in (None,identity):
            report['csv_ownership']='conflicting_new_capture'
            raise RuntimeError('Another CSV capture started')
        report['csv_id']=identity
        report['csv_ownership']='confirmed_new_guid'


def window(args):
    bridge, pc, out = context(args)
    before = {p:(p.stat().st_size,p.stat().st_mtime_ns) for p in profile.CSV_DIR.glob('*.csv')}
    report = {'case':args.case,'label':args.label,'input':'operator','limit_s':args.seconds,
              'status':'running','samples':[],'cleanup':[],'csv':[]}
    report['csv_preflight']=require_idle_csv(profile.LOG.read_text(encoding='utf-8',errors='replace'))
    tail = profile.LogTail(profile.LOG)
    started = time.monotonic();low_since=None;slow=0;csv_requested=False
    report['csv_ownership']='not_requested'
    try:
        csv_requested=True
        report['csv_ownership']='requested_unconfirmed'
        bridge.console('CsvProfile START')
        while time.monotonic()-started < args.seconds:
            now = time.monotonic();sample = profile.host_sample(args.editor_pid)
            sample['elapsed_s'] = round(now-started,3)
            low_since = (now if low_since is None else low_since) if sample['available_ram_fraction']<.15 else None
            if low_since is not None and now-low_since>=3: raise RuntimeError('Low RAM for3seconds')
            recent = tail.read()
            observe_csv(report,recent)
            if FAULT.search(recent): raise RuntimeError('New native/GPU fault')
            if now-started>=5 and not report.get('csv_id'): raise RuntimeError('CSV start was not confirmed')
            stats=bridge.call('editor_get_performance_stats');sample.update(stats)
            frame=float(stats['frame_ms'])
            if not math.isfinite(frame) or frame<=0: raise RuntimeError('Invalid native frame sample')
            slow=slow+1 if frame>250 else 0
            if slow>=3: raise RuntimeError('Three consecutive smoothed frame samples above250ms')
            live=bridge.call('editor_get_state')
            if not live.get('pie_running'): raise RuntimeError('PIE ended during window')
            sample['flow']=bridge.flow(pc['path'])
            report['samples'].append(sample);save(out/'checkpoint.json',report)
        report['status']='complete'
    except (Exception,KeyboardInterrupt) as error:
        report.update(status='aborted',reason=str(error) or 'operator interruption')
    finally:
        if report['csv_ownership']=='confirmed_new_guid':
            try: observe_csv(report,tail.read())
            except Exception as error:
                if report['csv_ownership']=='confirmed_new_guid':report['csv_ownership']='unknown_after_log_error'
                report['cleanup'].append({'action':'recheck CSV ownership','error':str(error)})
        # START can time out after being queued. Passively collect a delayed
        # GUID for at most5s, without issuing another native request. Without
        # ownership evidence, never STOP a recorder that may belong elsewhere.
        if csv_requested and report['csv_ownership']=='requested_unconfirmed':
            until=time.monotonic()+5
            while time.monotonic()<until and report['csv_ownership']=='requested_unconfirmed':
                try: observe_csv(report,tail.read())
                except Exception as error:
                    report['cleanup'].append({'action':'resolve CSV ownership','error':str(error)})
                    break
                if report['csv_ownership']=='requested_unconfirmed':time.sleep(.25)
        actions=[]
        owned=report['csv_ownership']=='confirmed_new_guid'
        if owned: actions.append(('stop owned CSV',lambda:bridge.console('CsvProfile STOP',2)))
        if owned and report['status']!='complete': actions.append(('request normal PIE stop',lambda:bridge.call('editor_stop_pie',timeout=2)))
        if csv_requested and not owned:
            report['cleanup'].append({'action':'leave unowned recorder and PIE unchanged',
                                      'error':'Capture ownership unconfirmed/refused; root must inspect before another trial'})
        for name,action in actions:
            try: report['cleanup'].append({'action':name,'result':action()})
            except Exception as error: report['cleanup'].append({'action':name,'error':str(error)})
        report['elapsed_s']=round(time.monotonic()-started,3);save(out/'report.json',report)
    report['csv']=completed_csv(report,before)
    report['functional_acceptance']='operator_review_required'
    report['hitch_acceptance']='unverified'
    if report['status']=='complete' and report['csv']:
        report['hitch_acceptance']='fail' if any(row['summary']['hitches_over_50_ms'] for row in report['csv']) else 'zero_over50ms_in_this_window'
    report['foreground_samples_all_true']=bool(report['samples']) and all(row['editor_foreground'] for row in report['samples'])
    save(out/'report.json',report)
    print(json.dumps({'report':str(out/'report.json'),'status':report['status'],'hitch_acceptance':report['hitch_acceptance']}))
    return 0 if report['status']=='complete' and report['csv'] and not any('error' in row for row in report['cleanup']) else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',nargs='?',default='plan',choices=['plan','snapshot','window'])
    parser.add_argument('--case',choices=CASES);parser.add_argument('--label')
    parser.add_argument('--owner');parser.add_argument('--editor-pid',type=int)
    parser.add_argument('--seconds',type=float,default=30.)
    args=parser.parse_args()
    if args.mode=='plan':print(PLAN);return 0
    if not args.case or not args.label or not re.fullmatch(r'[a-z0-9_-]{1,48}',args.label):
        parser.error('live modes require --case and a short lowercase --label')
    if not args.owner or not args.editor_pid:parser.error('live modes require existing root --owner and --editor-pid')
    if not math.isfinite(args.seconds) or not 1<=args.seconds<=60:parser.error('--seconds must be1..60')
    return snapshot(args) if args.mode=='snapshot' else window(args)


if __name__=='__main__':raise SystemExit(main())
