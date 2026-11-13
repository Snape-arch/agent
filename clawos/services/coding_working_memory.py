"""Build a bounded model view of an active coding run."""

from __future__ import annotations

import json


class CodingWorkingMemory:
    PROMPT_BYTES = 20_000
    INITIAL_BYTES = 10_000

    def __init__(self):
        self.retrievals = {}
        self.sent = []
        self.earliest_observation = 0

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    @classmethod
    def size(cls, value):
        return len(cls.encode(value).encode('utf-8'))

    @classmethod
    def initial(cls, objective, manifest, reproduction, commands, tests):
        """Pin the task contract and spend the rest on exact repository evidence."""
        packet = {
            'objective': objective,
            'frozen_test_commands': commands,
            'baseline_results': [{**row, 'stdout': row['stdout'][-400:], 'stderr': row['stderr'][-850:]}
                                 for row in tests],
            'context_digest': manifest['context_digest'],
            'writable_paths': manifest['scope']['write_paths'],
            'instruction_hierarchy': manifest['instruction_hierarchy'],
            'failure_frames': manifest['failure_frames'],
            'public_tests': reproduction.get('public_tests', []),
            'source_anchors': [],
            'source_map': [],
        }
        # Keep the original contract even when an unusually long request
        # leaves little room for optional source excerpts.
        for field in ('public_tests', 'instruction_hierarchy'):
            if cls.size(packet) > cls.INITIAL_BYTES:
                packet[field] = [{**row, 'content': row['content'][:250]} for row in packet[field]]
        for anchor in reproduction.get('source_anchors', []):
            cls._fit(packet, 'source_anchors', anchor, cls.INITIAL_BYTES)
        for row in manifest['code_evidence']:
            item = {'path': row['path'], 'symbols': [symbol['name'] for symbol in row['symbols'][:6]]}
            if not any(anchor['path'] == row['path'] for anchor in packet['source_anchors']):
                item.update(start_line=row['start_line'], excerpt=row['content'][:500])
            cls._fit(packet, 'source_map', item, cls.INITIAL_BYTES)
        return cls.encode(packet)

    @classmethod
    def _fit(cls, packet, key, value, limit):
        packet[key].append(value)
        if cls.size(packet) > limit:
            packet[key].pop()

    @classmethod
    def retrieval_key(cls, action, *, compact):
        fields = ('action', 'path', 'start_line', 'end_line', 'symbol', 'query', 'glob')
        return cls.encode({name: action[name] for name in fields if name in action} | {'compact': compact})

    def prompt(self, messages, observations, *, remaining, writable):
        guidance = {
            'turns_remaining_after_this_action': remaining,
            'writable_paths': writable,
            'instruction': (
                'Submit a patch as soon as you have the relevant definitions. Preserve all requirements. '
                'Read only evidence that can change the patch. Use refresh=true to request a repeated lookup.'
                if remaining > 1 else
                'Use the evidence now to submit a patch covering the full task. Avoid another lookup unless essential.'
            ),
        }
        if len(messages) == 2:
            result = [messages[0], {**messages[1], 'content': messages[1]['content'] + '\n' + self.encode(guidance)}]
        else:
            latest = self._bounded_feedback(json.loads(messages[-1]['content']))
            # Keep a short description of the last action and the freshest
            # result. Older raw messages stay available to the runner.
            try:
                action = json.loads(messages[-2]['content'])
                label = action.get('action', 'propose_patch') if isinstance(action, dict) else 'invalid'
            except ValueError:
                label = 'invalid'
            result = [*messages[:2], {'role': 'assistant', 'content': self.encode({'action': str(label)[:32]})},
                      {'role': 'user', 'content': ''}]
            recall = {'earlier_failures': [], 'earlier_source_reads': [], 'earlier_searches': []}

            def render():
                result[-1]['content'] = '\n'.join(map(self.encode, (latest, guidance, recall)))
                return self.size(result)

            if render() > self.PROMPT_BYTES:
                latest = self._bounded_feedback(latest, excerpt_limit=600)
            seen = set()
            current = latest.get('observation', {})
            current_reads = current.get('results', [current])
            seen.update((item['path'], item['start_line'], item['end_line']) for item in current_reads
                        if item.get('type') == 'read')
            older = list(reversed(observations[self.earliest_observation:]))
            for observation in older:
                if current.get('turn') is not None and current['turn'] == observation.get('turn'):
                    continue
                if observation['type'] in ('patch_result', 'proposal_error', 'patch_execution_error'):
                    item = {'turn': observation.get('turn'), 'type': observation['type'],
                            'failure': str(observation.get('failure') or observation.get('error') or '')[:350]}
                    if observation.get('rounds'):
                        tests = observation['rounds'][-1].get('tests', [])
                        item['test_failures'] = [(test.get('stderr') or test.get('stdout') or '')[-400:]
                                                 for test in tests if test.get('exit_code') != 0][:2]
                    self._remember(recall, 'earlier_failures', item, render, 3)
            for observation in older:
                items = observation.get('results', [observation])
                for item in reversed(items):
                    if item.get('type') == 'search' and item not in current_reads:
                        summary = {'query': item['query'], 'locations': [
                            {k: match[k] for k in ('path', 'line')} for match in item['matches'][:4]]}
                        if summary not in recall['earlier_searches']:
                            self._remember(recall, 'earlier_searches', summary, render, 3)
                        continue
                    if item.get('type') != 'read' or not item.get('content'):
                        continue
                    key = (item['path'], item['start_line'], item['end_line'])
                    if key in seen:
                        continue
                    seen.add(key)
                    entry = {k: item[k] for k in ('path', 'start_line', 'end_line', 'truncated')}
                    entry['content'] = item['content'][:850]
                    entry['end_line'] = entry['start_line'] + entry['content'].count('\n')
                    entry['truncated'] = entry['truncated'] or len(entry['content']) != len(item['content'])
                    self._remember(recall, 'earlier_source_reads', entry, render, 8)
            render()
        self.sent.append(self.size(result))
        return result

    def _remember(self, recall, key, item, render, count):
        entries = recall[key]
        if len(entries) < count:
            entries.append(item)
            if render() > self.PROMPT_BYTES:
                entries.pop()

    @staticmethod
    def _bounded_feedback(payload, *, excerpt_limit=1350):
        observation = payload.get('observation')
        if not observation:
            return payload
        if observation.get('anchor_diagnostics'):
            diagnostics = observation['anchor_diagnostics']
            excerpts = []
            for excerpt in diagnostics['excerpts'][:3]:
                row = dict(excerpt)
                if 'unique_prefix_through_match_line' in row:
                    row.pop('content', None)
                elif 'content' in row:
                    row['content'] = row['content'][:850]
                excerpts.append(row)
            return {'observation': {**observation, 'anchor_diagnostics': {**diagnostics, 'excerpts': excerpts}}}
        if observation.get('type') not in ('inspect', 'read', 'search', 'symbols', 'semantic'):
            return payload
        def compact(item):
            row = dict(item)
            if row.get('type') == 'read' and len(row['content']) > excerpt_limit:
                row['content'] = row['content'][:excerpt_limit]
                row['end_line'] = row['start_line'] + row['content'].count('\n')
                row['truncated'] = True
            for key, limit in (('matches', 6), ('symbols', 12), ('nodes', 8), ('edges', 12)):
                if key in row and len(row[key]) > limit:
                    row[key] = row[key][:limit]
                    row['truncated'] = True
            return row
        view = compact(observation)
        if view.get('type') == 'inspect':
            view['results'] = [compact(item) for item in view['results']]
        return {'observation': view}
