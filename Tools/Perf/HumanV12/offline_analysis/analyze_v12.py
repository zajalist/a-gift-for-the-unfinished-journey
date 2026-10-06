"""Read captured V12 evidence; write only this lane's offline analysis outputs."""
from __future__ import annotations
import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'Saved/Verification/human_profile_analysis_20261001/offline_analysis'
CSV = ROOT / 'Saved/Profiling/CSV/Profile(20261001_201718).csv'
CAPTURE = ROOT / 'Saved/Verification/live_completion_20261001/human_profile_v12/capture.json'
LOG = ROOT / 'Saved/Verification/live_completion_20261001/human_profile_v12/streaming-and-gameplay.log'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def percentile(values, pct):
    values = sorted(values)
    return values[min(len(values)-1, max(0, math.ceil(len(values)*pct/100)-1))] if values else None


def summarize(rows):
    result = {'frames': len(rows), 'wall_frames_over_50ms': sum(r['FrameTime'] > 50 for r in rows),
              'near_3fps_wall_frames': sum(abs(r['FrameTime']-1000/3) <= 0.1 for r in rows)}
    for name in ('FrameTime', 'GameThreadTime', 'GPUTime', 'RenderThreadTime'):
        values = [r[name] for r in rows]
        result[name] = {'p50_ms': percentile(values, 50), 'p95_ms': percentile(values, 95), 'max_ms': max(values) if values else None}
    return result


def main():
    raw = list(csv.reader(CSV.open(encoding='utf-8', newline='')))
    if raw[-2][0] != 'EVENTS' or raw[-1][0] != '[HasHeaderRowAtEnd]':
        raise ValueError('Expected UE ending header and metadata')
    header, metadata = raw[-2], raw[-1]
    meta = {metadata[i][1:-1]: metadata[i+1] for i in range(0, len(metadata)-1, 2) if metadata[i].startswith('[')}
    capture = json.loads(CAPTURE.read_text(encoding='utf-8'))
    log_text = LOG.read_bytes().decode('utf-8')
    frames, event_rows, cumulative = [], {}, 0.
    for index, values in enumerate(raw[1:-2]):
        # The opening header grows during capture. Ending columns retain append
        # order. Preserve repeated counters with occurrence suffixes.
        row, occurrences = {}, {}
        for column, name in enumerate(header):
            if name == 'EVENTS' or column >= len(values) or not values[column]:
                continue
            occurrences[name] = occurrences.get(name, 0)+1
            key = name if occurrences[name] == 1 else f'{name} [occurrence {occurrences[name]}]'
            row[key] = float(values[column])
        row.update(frame_index=index, elapsed_start_s=cumulative, events=values[0], raw_column_count=len(values))
        cumulative += row['FrameTime']/1000
        row['elapsed_end_s'] = cumulative
        if values[0]:
            event_rows[index] = row
        frames.append(row)
    # Native event elapsed times provide a subsecond UTC origin. Metadata's
    # starttimestamp has integer-second precision and is only a cross-check.
    anchors, parsed_log = [], []
    expression = re.compile(r'^\[(\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3})\]\[([^]]*)\](.*)$')
    for line_number, line in enumerate(log_text.split('\n'), 1):
        line = line.rstrip('\r')
        match = expression.match(line)
        if not match:
            continue
        stamp = dt.datetime.strptime(match[1], '%Y.%m.%d-%H.%M.%S:%f').replace(tzinfo=dt.timezone.utc).timestamp()
        entry = {'line': line_number, 'utc': iso(stamp), 'timestamp': stamp, 'message': match[3]}
        parsed_log.append(entry)
        gc = re.search(r'CSVEvent "GC" \[Frame (\d+)\]', line)
        if gc and int(gc[1]) in event_rows:
            event = event_rows[int(gc[1])]['events']
            elapsed = float(re.search(r'GC##([0-9.]+)', event)[1])
            anchors.append({'frame': int(gc[1]), 'utc_origin_epoch': stamp-elapsed, 'log_line': line_number})
    origin = statistics.median(a['utc_origin_epoch'] for a in anchors)
    samples = capture['samples']
    times = [dt.datetime.fromisoformat(s['utc']).timestamp() for s in samples]
    intervals = []
    for left, right, start, end in zip(samples, samples[1:], times, times[1:]):
        kind = ('sample_bracket_foreground' if left['editor_foreground'] else 'sample_bracket_background') if left['editor_foreground'] == right['editor_foreground'] else 'focus_transition_uncertain'
        intervals.append({'start_utc': iso(start), 'end_utc': iso(end), 'duration_s': end-start, 'classification': kind})
    for row in frames:
        start, end = origin+row['elapsed_start_s'], origin+row['elapsed_end_s']
        row['utc_start'], row['utc_end'] = iso(start), iso(end)
        low = bisect.bisect_right(times, start)-1
        high = bisect.bisect_left(times, end)
        if low < 0 or high >= len(times):
            row['focus_classification'] = 'outside_sample_brackets'
        else:
            states = {samples[i]['editor_foreground'] for i in range(low, high+1)}
            row['focus_classification'] = ('sample_bracket_foreground' if True in states else 'sample_bracket_background') if len(states) == 1 else 'focus_transition_uncertain'
    def detail(row):
        previous = frames[max(0, row['frame_index']-1)]
        keys = ('frame_index','utc_start','utc_end','FrameTime','GameThreadTime','GPUTime','focus_classification',
                'Exclusive/GameThread/AsyncLoading','FileIO/GameThread/AsyncLoadingTime','Exclusive/GameThread/GarbageCollectionFull',
                'Exclusive/GameThread/GarbageCollection','Exclusive/GameThread/Audio','Exclusive/GameThread/AddToWorld',
                'Exclusive/GameThread/EventWait','Exclusive/GameThread/TimerManager','FileIO/ExistingQueuedPackagesQueueDepth')
        result = {k: row.get(k, 0) for k in keys}
        result['preceding_row'] = {k: previous.get(k, 0) for k in ('frame_index','GameThreadTime','Exclusive/GameThread/EventWait','Exclusive/GameThread/GarbageCollectionFull')}
        result['nearby_log_entries'] = [{k:v for k,v in event.items() if k != 'timestamp'} for event in parsed_log if origin+row['elapsed_start_s']-0.25 <= event['timestamp'] <= origin+row['elapsed_end_s']+0.25]
        return result
    classifications = sorted({r['focus_classification'] for r in frames})
    summary = {'input_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (CSV,CAPTURE,LOG)},
               'csv_metadata': {k:meta.get(k) for k in ('csvid','starttimestamp','endtimestamp','captureduration','targetframerate','namedevents','hasgtstalls','deviceprofile','gpu','raytracing')},
               'frame_count':len(frames),'opening_header_columns':len(raw[0]),'ending_header_columns':len(header),
               'row_widths': sorted({r['raw_column_count'] for r in frames}),
               'alignment': {'utc_origin':iso(origin),'method':'median(native logged GC UTC minus CSV GC event timestamp)',
                             'anchors':anchors,'anchor_spread_ms':1000*(max(a['utc_origin_epoch'] for a in anchors)-min(a['utc_origin_epoch'] for a in anchors)),
                             'frame_time_sum_s':cumulative,'metadata_duration_s':float(meta['captureduration']),
                             'frame_time_sum_minus_metadata_ms':1000*(cumulative-float(meta['captureduration'])),
                             'host_elapsed_offset_range_s':[min(t-s['elapsed_s']-origin for t,s in zip(times,samples)),max(t-s['elapsed_s']-origin for t,s in zip(times,samples))]},
               'all_frames':summarize(frames),'by_focus_bracket':{kind:summarize([r for r in frames if r['focus_classification']==kind]) for kind in classifications},
               'foreground_wall_frames_over_50ms':[detail(r) for r in frames if r['focus_classification']=='sample_bracket_foreground' and r['FrameTime']>50],
               'largest_wall_frames':[detail(r) for r in sorted(frames,key=lambda x:x['FrameTime'],reverse=True)[:4]],
               'largest_game_thread_frames':[detail(r) for r in sorted(frames,key=lambda x:x['GameThreadTime'],reverse=True)[:12]],
               'host_samples': {'count':len(samples),'median_spacing_s':statistics.median(b-a for a,b in zip(times,times[1:])),
                                'max_spacing_s':max(b-a for a,b in zip(times,times[1:])),
                                'available_ram_gib_range':[min(s['available_ram_gib'] for s in samples),max(s['available_ram_gib'] for s in samples)],
                                'editor_working_set_gib_range':[min(s['unreal_working_set_gib'] for s in samples),max(s['unreal_working_set_gib'] for s in samples)]},
               'limits':['Host focus sampling is coarse; matching bracketing samples cannot prove no intervening focus changes.',
                         'UTC uses actual event timestamps; capture elapsed_s starts from another monotonic origin and is not used to align CSV.',
                         'Wall FrameTime and CPU work can differ by one record; preceding-row event waits and GC must be inspected.',
                         'Generic EventWait does not name the waiter/caller. Capture has namedevents=0 and hasgtstalls=0.',
                         'This is editor PIE with an explicit 30fps foreground limit, not a packaged uncapped benchmark.',
                         'Current source can include edits after V12; current callsites establish candidates, not exact executed revisions.',
                         'No gameplay, profiling, GPU jobs, tests, builds, editor or source mutations were performed.']}
    OUT.mkdir(parents=True, exist_ok=True)
    for name,value in [('analysis.json',summary),('focus_intervals.json',intervals),('log_events.json',[e for e in parsed_log if not e['message'].startswith('LogHaybaMCP')])]:
        (OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    selected = ['frame_index','utc_start','utc_end','elapsed_start_s','elapsed_end_s','focus_classification','FrameTime','GameThreadTime','GPUTime','Exclusive/GameThread/EventWait','Exclusive/GameThread/GarbageCollectionFull','Exclusive/GameThread/GarbageCollection','Exclusive/GameThread/AsyncLoading','Exclusive/GameThread/AddToWorld','Exclusive/GameThread/Audio','Exclusive/GameThread/TimerManager','FileIO/ExistingQueuedPackagesQueueDepth','events']
    with (OUT/'frames.csv').open('w',encoding='utf-8',newline='') as target:
        writer=csv.DictWriter(target,fieldnames=selected,extrasaction='ignore');writer.writeheader();writer.writerows(frames)
    print(json.dumps({k:summary[k] for k in ('frame_count','alignment','by_focus_bracket','host_samples')},indent=2))


if __name__=='__main__':
    main()
