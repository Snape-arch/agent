"""Issue-only controls for ten historical Python repository fixes."""


def case(identifier, project, fix, objective, public, heldout):
    return dict(id=identifier, project=project, fix=fix, objective=objective, public=public, heldout=heldout)


CASES = (
    case('barrel-delete', 'boltons', '574393a4c349d5b81ee328a9e450c34dd0614635',
         'Deleting a slice spanning several barrels leaves wrong elements or length. Preserve normal list slice deletion semantics.',
         '''from boltons.listutils import BarrelList
value = BarrelList()
value.lists = [list(range(i, i + 3)) for i in range(0, 12, 3)]
del value[2:10]
assert list(value) == [0, 1, 10, 11] and len(value) == 4
''', '''from boltons.listutils import BarrelList
for start, stop in ((1, 7), (4, 10), (2, 4), (3, 9)):
    expected = list(range(12))
    value = BarrelList()
    value.lists = [expected[i:i+3] for i in range(0, 12, 3)]
    del expected[start:stop]
    del value[start:stop]
    assert list(value) == expected and len(value) == len(expected)
'''),
    case('empty-bits', 'boltons', 'efff866a3b66fdafc817894390742e1d8bc025e5',
         'A zero-length Bits value must round-trip through empty binary, hexadecimal and bytes representations. Preserve validation of unsupported inputs.',
         '''from boltons.mathutils import Bits
assert Bits('').as_hex() == ''
assert Bits.from_hex('') == Bits('')
''', '''from boltons.mathutils import Bits
bits = Bits('101')[:0]
assert len(bits) == 0 and bits.as_bin() == '' and bits.as_list() == []
assert bits.as_bytes() == b'' and Bits.from_bytes(bits.as_bytes()) == bits
assert Bits.from_hex(bits.as_hex()) == bits
'''),
    case('empty-names', 'boltons', '970051b66474ac37383c5d990c169c794e20eb88',
         'Both named record factories must raise ValueError for an empty type name or empty field name, while continuing to accept valid names.',
         '''from boltons.namedutils import namedtuple
try:
    namedtuple('Point', ['x', ''])
except ValueError:
    pass
else:
    raise AssertionError('empty field must raise ValueError')
''', '''from boltons.namedutils import namedtuple, namedlist
for factory in (namedtuple, namedlist):
    for name, fields in (('', ['x']), ('Point', ['']), ('Point', ['x-y'])):
        try:
            factory(name, fields)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid name accepted')
    assert factory('Point', ['x', 'y'])(1, 2).y == 2
'''),
    case('iterator-values', 'boltons', 'a1ea1030ed85137e999c0bd9b11d16368d3ab241',
         'Adding a one-shot iterable of values to an ordered multi-value mapping corrupts its values. Fix the behavior for the base mapping and URL query parameter mapping, including empty iterators.',
         '''from boltons.dictutils import OrderedMultiDict
m = OrderedMultiDict()
m.addlist('a', iter([1, 2, 3]))
assert m.getlist('a') == [1, 2, 3] and m.get('a') == 3
''', '''from boltons.dictutils import OrderedMultiDict
from boltons.urlutils import QueryParamDict
for mapping in (OrderedMultiDict(), QueryParamDict()):
    mapping.addlist('empty', iter(()))
    mapping.addlist('key', (x for x in ['a', 'b']))
    assert mapping.keys() == ['key']
    assert mapping.getlist('key') == ['a', 'b'] and mapping.get('key') == 'b'
'''),
    case('complement-order', 'boltons', 'ec1ff9f6728f5f857402b294c218be731c62af5f',
         'Non-strict subset and superset comparisons fail for two complement sets. They should reverse the subset ordering of their excluded elements and handle equality.',
         '''from boltons.setutils import complement
assert complement('ab') <= complement('a')
''', '''from boltons.setutils import complement
a, ab = complement('a'), complement('ab')
assert a >= ab and ab >= ab and ab <= ab and not a <= ab
'''),
    case('indexed-negative', 'boltons', 'd0a284fc7ef1aebceb54798600d73be4eeb76ed8',
         'After a deletion in an IndexedSet, out-of-range negative indexing and pop can silently wrap around. Both must raise IndexError and preserve valid negative indexes.',
         '''from boltons.setutils import IndexedSet
value = IndexedSet(range(10))
value.pop(2)
try:
    value[-10]
except IndexError:
    pass
else:
    raise AssertionError('out-of-range negative index accepted')
''', '''from boltons.setutils import IndexedSet
value = IndexedSet(range(10))
value.pop(2)
before = list(value)
assert value[-1] == 9 and value[-9] == 0
try:
    value.pop(-15)
except IndexError:
    pass
else:
    raise AssertionError('out-of-range negative pop accepted')
assert list(value) == before
'''),
    case('singular-double-s', 'boltons', '1e61524a798ea73632029a013a7686036d5c126f',
         'Already singular words ending with double s are losing their final letter. Keep case and preserve handling of genuine plurals.',
         '''from boltons.strutils import singularize
assert singularize('glass') == 'glass'
''', '''from boltons.strutils import singularize
assert singularize('BOSS') == 'BOSS' and singularize('address') == 'address'
assert singularize('classes') == 'class' and singularize(singularize('Glasses')) == 'Glass'
'''),
    case('ordered-copy', 'boltons', 'ebc7a8f776debfa33f0b380b57a444bca75a251b',
         'The standard copy and deepcopy operations collapse repeated entries in an ordered multi-value dictionary. Preserve value order, and ensure a deep copy does not share mutable values.',
         '''from copy import copy
from boltons.dictutils import OrderedMultiDict
m = OrderedMultiDict([('a', 1), ('a', 2), ('b', 3)])
assert copy(m).getlist('a') == [1, 2]
''', '''from copy import deepcopy
from boltons.dictutils import OrderedMultiDict
m = OrderedMultiDict([('x', [1]), ('x', [2])])
result = deepcopy(m)
assert result.getlist('x') == [[1], [2]]
result.getlist('x')[0].append(9)
assert m.getlist('x') == [[1], [2]]
'''),
    case('binary-unit-edge', 'boltons', '766b5547392fe8d54c1e000098499dc556bb5cb7',
         'Byte-size formatting should roll over at exact powers of 1024. Keep the old unit just below the boundary and preserve sign and decimal precision.',
         '''from boltons.strutils import bytes2human
assert bytes2human(1024 ** 2) == '1M'
''', '''from boltons.strutils import bytes2human
assert bytes2human(-(1024 ** 3)) == '-1G'
assert bytes2human(1023) == '1023B'
assert bytes2human(1024, 2) == '1.00K'
'''),
    case('interpose-empty', 'toolz', 'd2eba0374a452c2b18fe188b04527e22bda3548c',
         'Interposing a separator into an empty sequence should yield an empty iterator instead of raising StopIteration. Keep separator placement for nonempty inputs.',
         '''from toolz import interpose
assert list(interpose('x', [])) == []
''', '''from toolz import interpose
assert list(interpose(None, iter(()))) == []
assert list(interpose('x', iter([1, 2, 3]))) == [1, 'x', 2, 'x', 3]
'''),
)
