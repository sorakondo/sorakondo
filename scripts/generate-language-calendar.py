"""Render contribution calendars colored by commit repository primary language."""
import collections
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import subprocess

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner primaryLanguage { name color } }
        contributions(first: 100, after: $cursor) {
          nodes { occurredAt commitCount }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
"""


def fetch(login):
    pending, visited = [None], set()
    commits, colors, days = {}, {}, []
    while pending:
        cursor = pending.pop()
        if cursor in visited:
            continue
        visited.add(cursor)
        result = subprocess.run(
            ['gh', 'api', 'graphql', '--input', '-'],
            input=json.dumps({'query': QUERY, 'variables': {'login': login, 'cursor': cursor}}),
            text=True, capture_output=True, check=True,
        )
        payload = json.loads(result.stdout)
        if payload.get('errors'):
            raise RuntimeError(payload['errors'])
        data = payload['data']['user']['contributionsCollection']
        if not days:
            days = [day for week in data['contributionCalendar']['weeks']
                    for day in week['contributionDays']]
        for entry in data['commitContributionsByRepository']:
            repo = entry['repository']
            language = repo['primaryLanguage'] or {'name': 'Other activity', 'color': '#8b949e'}
            name = language['name']
            colors[name] = language['color'] or '#8b949e'
            for node in entry['contributions']['nodes']:
                day = node['occurredAt'][:10]
                commits[(repo['nameWithOwner'], day)] = (name, node['commitCount'])
            page = entry['contributions']['pageInfo']
            if page['hasNextPage'] and page['endCursor'] not in visited:
                pending.append(page['endCursor'])
    by_day = collections.defaultdict(collections.Counter)
    for (_, day), (name, count) in commits.items():
        by_day[day][name] += count
    return days, by_day, colors


def shade(color, factor):
    return '#' + ''.join(f'{round(int(color[i:i+2], 16) * factor):02x}' for i in (1, 3, 5))


def render(days, by_day, colors, dark):
    background, foreground, empty = ('#0d1117', '#e6edf3', '#21262d') if dark else ('#ffffff', '#1f2328', '#ebedf0')
    first = dt.date.fromisoformat(days[0]['date'])
    offset = (first.weekday() + 1) % 7
    totals = sum(by_day.values(), collections.Counter())
    legend = [(name, colors[name]) for name, _ in totals.most_common()]
    if not any(name == 'Other activity' for name, _ in legend):
        legend.append(('Other activity', '#8b949e'))
    height = 440 + math.ceil(len(legend) / 4) * 30
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="{height}" viewBox="0 0 1280 {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">Contributions by repository primary language</title>',
             '<desc id="desc">Height represents daily contributions. Color represents the primary language with the most commits that day. Non-commit activity is gray.</desc>',
             f'<rect width="1280" height="{height}" rx="12" fill="{background}"/>',
             f'<g font-family="Segoe UI,Arial,sans-serif" fill="{foreground}">',
             '<text x="32" y="38" font-size="24" font-weight="600">Isometric Calendar · Languages</text>',
             '<text x="32" y="64" font-size="14">Color: dominant repository primary language per day · Height: contribution count</text>']
    cubes = []
    for index, day in enumerate(days):
        week, weekday = divmod(offset + index, 7)
        x, y = 160 + week * 19 - weekday * 16, 150 + week * 3 + weekday * 12
        count = day['contributionCount']
        language = by_day.get(day['date'], collections.Counter()).most_common(1)
        name = language[0][0] if language else 'Other activity'
        color = colors.get(name, '#8b949e') if count else empty
        h = 3 + min(68, math.log2(count + 1) * 12)
        label = html.escape(f"{day['date']}: {count} contributions · {name if count else 'No activity'}")
        cube = [f'<g><title>{label}</title>']
        for points, fill in [
            ([(x-8, y), (x, y+6), (x, y+6-h), (x-8, y-h)], shade(color, .72)),
            ([(x, y+6), (x+8, y), (x+8, y-h), (x, y+6-h)], shade(color, .88)),
            ([(x, y-6-h), (x+8, y-h), (x, y+6-h), (x-8, y-h)], color),
        ]:
            cube.append(f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in points)}" fill="{fill}"/>')
        cube.append('</g>')
        cubes.append((y, ''.join(cube)))
    parts.extend(cube for _, cube in sorted(cubes))
    for i, (name, color) in enumerate(legend):
        x, y = 32 + (i % 4) * 305, 406 + (i // 4) * 30
        parts.extend([f'<rect x="{x}" y="{y-12}" width="14" height="14" rx="3" fill="{color}"/>',
                      f'<text x="{x+22}" y="{y}" font-size="14">{html.escape(name)}</text>'])
    parts.append(f'<text x="32" y="{height-14}" font-size="12">{days[0]["date"]} – {days[-1]["date"]} · Up to 100 repositories · Repository language, not individual file language</text></g></svg>')
    return '\n'.join(parts) + '\n'


if __name__ == '__main__':
    days, by_day, colors = fetch(os.environ.get('USERNAME', 'sorakondo'))
    output = Path('profile-3d-contrib')
    output.mkdir(exist_ok=True)
    for mode in ('light', 'dark'):
        (output / f'profile-languages-{mode}.svg').write_text(render(days, by_day, colors, mode == 'dark'))
