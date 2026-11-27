"""Build an end-of-day recap from the lab's timestamped, publishable event records."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Kolkata')
PARTICIPATION = {'team', 'proposal', 'critique', 'decision', 'candidate', 'review'}
LABELS = {
    'team': 'Staffed', 'proposal': 'Proposed', 'critique': 'Challenged', 'decision': 'Decided',
    'candidate': 'Built', 'review': 'Reviewed', 'check': 'Tested',
    'release': 'Release', 'outcome': 'Outcome',
}


def local_day(timestamp):
    try:
        return datetime.fromisoformat(timestamp).astimezone(ZONE).date()
    except (ValueError, TypeError):
        return None


def summarize_day(runs, day, closed):
    agents = {}
    collaborations = Counter()
    counts = Counter()
    work = []
    for run in sorted(runs, key=lambda item: item.get('started', ''), reverse=True):
        events = [event for event in run['events'] if local_day(event.get('at')) == day]
        if not events and local_day(run.get('started')) != day:
            continue
        people = set()
        contributions = []
        decisions = []
        results = []
        for event in events:
            kind, title = event['kind'], event['title']
            actor = event.get('actor') or 'Lab'
            body = event.get('body', '')
            entry = {'kind': kind, 'title': title, 'body': body[:1200], 'actor': actor,
                     'model': event.get('model', ''), 'provider': event.get('provider', ''), 'at': event['at']}
            if kind in PARTICIPATION or (kind == 'check' and event.get('model') and title == 'Synthetic routing trial'):
                people.add(actor)
                if actor not in agents:
                    agents[actor] = {'name': actor, 'counts': Counter(), 'runs': set(), 'models': set()}
                agent = agents[actor]
                agent['counts'][kind] += 1
                agent['runs'].add(run['id'])
                if entry['model']:
                    route = ' · '.join(filter(None, (entry['provider'], entry['model'])))
                    agent['models'].add(route)
            if kind in {'team', 'proposal', 'critique'}:
                counts[kind] += 1
                contributions.append(entry)
            if kind == 'idea':
                entry['disposition'] = event.get('disposition', '')
                entry['author'] = event.get('author', '')
                counts['idea_' + entry['disposition']] += 1
                decisions.append(entry)
            if kind == 'decision':
                disposition = event.get('disposition')
                if not disposition:
                    if run.get('outcome') == 'The panel found insufficient evidence for a code change.':
                        disposition = 'deferred'
                    elif any(item['kind'] == 'candidate' or item['title'].startswith('Candidate construction')
                             for item in run['events']):
                        disposition = 'advanced'
                    else:
                        disposition = 'recorded'
                entry['disposition'] = disposition
                decisions.append(entry)
                counts[disposition] += 1
            if kind == 'review':
                if event.get('verdict') == 'request_changes' or title == 'Requested changes':
                    counts['changes'] += 1
                results.append(entry)
            if kind in {'check', 'candidate', 'release', 'outcome'}:
                results.append(entry)
            if kind == 'release' and title == 'Release state: deployed':
                counts['deployed'] += 1
        approvals = [event for event in run['events'] if event['kind'] == 'review' and event['title'] == 'Approved']
        outcomes = [event for event in run['events'] if event['kind'] == 'outcome']
        if outcomes:
            terminal = outcomes[-1]
            state = terminal.get('disposition')
            if local_day(terminal['at']) == day and state in {'rejected', 'failed'}:
                counts[state] += 1
        elif run.get('state') in {'rejected', 'failed'}:
            milestones = [event for event in run['events'] if event['kind'] in {'decision', 'check', 'review'}]
            if milestones and local_day(milestones[-1]['at']) == day:
                state = run['state']
                if not (state == 'rejected' and any(item['disposition'] == 'deferred' for item in decisions)):
                    counts[state] += 1
                results.append({'kind': 'outcome', 'title': 'Cycle ' + state, 'body': run.get('outcome', ''),
                                'actor': 'Lab', 'at': milestones[-1]['at']})
        if run.get('verified') and approvals and local_day(approvals[-1]['at']) == day:
            counts['verified'] += 1
            results.append({'kind': 'outcome', 'title': 'Verified improvement', 'body': run.get('outcome', ''),
                            'actor': 'Lab', 'at': approvals[-1]['at']})
        names = sorted(people)
        if len(names) > 1:
            collaborations[tuple(names)] += 1
        if events or local_day(run.get('started')) == day:
            work.append({'id': run['id'], 'topic': run['topic'], 'github': run.get('github', ''),
                         'people': names, 'contributions': contributions, 'decisions': decisions,
                         'results': sorted(results, key=lambda item: item['at'])})
    return {
        'day': day.isoformat(), 'closed': closed, 'timezone': ZONE.key, 'labels': LABELS,
        'counts': {**counts, 'runs': len(work), 'agents': len(agents)},
        'agents': [{**agent, 'runs': len(agent['runs']), 'models': sorted(agent['models'])}
                   for agent in sorted(agents.values(), key=lambda item: (-sum(item['counts'].values()), item['name']))],
        'collaborations': [{'people': list(people), 'runs': count} for people, count in collaborations.most_common()],
        'work': work,
    }


def publish_reports(state):
    records = sorted((state / 'records').glob('*.json'))
    runs = [json.loads(path.read_text()) for path in records]
    today = datetime.now(ZONE).date()
    by_day = defaultdict(list)
    for run in runs:
        days = {local_day(event.get('at')) for event in run['events']}
        days.add(local_day(run.get('started')))
        for day in days - {None}:
            by_day[day].append(run)
    first = min(by_day, default=today)
    cache_path = state / 'daily-report-hashes.json'
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    url = os.environ['PLANET_LAB_SITE'] + '/api/daily'
    token = (Path(os.environ['CREDENTIALS_DIRECTORY']) / 'sites.token').read_text().strip()
    auth = {'OAI-Sites-Authorization': f'Bearer {token}'}
    from lab import atomic
    for offset in range((today - first).days + 1):
        day = first + timedelta(days=offset)
        report = summarize_day(by_day[day], day, day < today)
        payload = json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode()
        digest = hashlib.sha256(payload).hexdigest()
        if report['closed'] and cache.get(report['day']) == digest:
            continue
        request = urllib.request.Request(url, payload, {**auth, 'Content-Type': 'application/json'}, method='PUT')
        with urllib.request.urlopen(request, timeout=15) as result:
            if json.load(result).get('day') != report['day']:
                raise RuntimeError('Daily report write was not acknowledged')
        readback = urllib.request.Request(url + '?day=' + report['day'], headers=auth)
        with urllib.request.urlopen(readback, timeout=15) as result:
            stored = json.load(result)
        if stored != report:
            raise RuntimeError('Daily report differed after hosted readback')
        if report['closed']:
            cache[report['day']] = digest
            atomic(cache_path, cache)
        print(f"Verified {'closed' if report['closed'] else 'current'} report for {report['day']}", flush=True)


if __name__ == '__main__':
    publish_reports(Path('/var/lib/personal-agent/planet-lab'))
