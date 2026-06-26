# Integration, Loaders, and Utilities

## JSON loader

Loads a `RegisterModel` from RDL-generated JSON.

```python
from cocotbext.ral.adapters import load_json

model = load_json("registers.json", model_name="my_ip")
print(f"Loaded {model.register_count} registers")
```

Expected JSON structure:

```json
{
  "type": "addrmap",
  "inst_name": "my_ip",
  "addr_offset": 0,
  "children": [
    {
      "type": "reg",
      "inst_name": "CTRL",
      "addr_offset": 0,
      "regsize": 32,
      "children": [
        {
          "type": "field",
          "inst_name": "enable",
          "lsb": 0, "msb": 0,
          "reset": 0,
          "sw_access": "rw",
          "woclr": 0
        }
      ]
    }
  ]
}
```

The `woclr` flag: `sw_access="rw"` + `woclr=1` maps to `SwAccess.W1C`.

Side-effect flags `woset` / `rclr` / `rset` map to `W1S` / `RCLR` / `RSET`
(or the `onwrite`/`onread` string forms). A field may also carry
`"encode": {"NAME": value, ...}` (enumeration) and `"counter": 1`
(hardware counter → volatile).

## RDL loader

Loads from SystemRDL source. Requires `systemrdl-compiler`.

```python
from cocotbext.ral.adapters import load_rdl

model = load_rdl(
    "regs.rdl",
    top_name="my_ip",           # top-level addrmap name
    incdir=["deps/rdl/"],       # include directories
    model_name="my_ip",
)
```

The loader honors the built-in SystemRDL `dontcompare` property as a
bidirectional signal on the field's `volatile` flag:

| RDL annotation                | Loaded `volatile` | Read-checked? |
| ----------------------------- | ----------------- | ------------- |
| (no annotation)               | inferred from access type (RO/RCLR/RSET → True; RW/W1C/W1S → False) | depends on access |
| `dontcompare;` or `= true;`   | True              | No            |
| `dontcompare = false;`        | False             | Yes (even for RO) |

Designers can therefore use `dontcompare = false;` on a static RO field
(IDs, versions, capability bits) to opt it into reset-value checking
without any Python-side override. For RDL the verification environment
can't edit, `RegisterModel.force_check_ro()` is the post-load
alternative (see Core Model docs).

The RDL loader also maps the `encode` property to a field enumeration and
the `counter` property to a volatile counter field.

## Memory regions

`Memory` provides `uvm_mem`-style access. Single-word and burst:

```python
mem = ral.get_memory("buf")          # attaches this RAL for bus access
await mem.write(0x10, 0xDEADBEEF)     # single word at base + 0x10
val = await mem.read(0x10)

await mem.write_block(0x0, [0xA, 0xB, 0xC])   # 3 words, 4-byte stride
words = await mem.read_block(0x0, count=3)
```

## Backdoor resolvers

### BackdoorResolver (base)

Returns `hdl_path` from the register/field spec directly.

```python
from cocotbext.ral.backdoor import BackdoorResolver

resolver = BackdoorResolver()
path = resolver.resolve_register_path(register)  # returns hdl_path or None
```

### PrefixBackdoorResolver

Prepends an instance prefix to spec paths. Ideal for tiled/replicated designs.

```python
from cocotbext.ral.backdoor import PrefixBackdoorResolver

resolver = PrefixBackdoorResolver(prefix="dut.gen_x[3].gen_y[4].tile")

# Spec hdl_path "ctrl_reg" -> "dut.gen_x[3].gen_y[4].tile.ctrl_reg"
path = resolver.resolve_register_path(register)
```

### MappingBackdoorResolver

Explicit name-to-path dictionaries for custom mappings.

```python
from cocotbext.ral.backdoor import MappingBackdoorResolver

resolver = MappingBackdoorResolver(
    register_paths={"block.CTRL": "dut.custom_path.ctrl_reg"},
    field_paths={"block.CTRL.enable": "dut.custom_path.ctrl_reg.en_bit"},
)
```

## Transaction logger

Writes detailed per-transaction records to a file.

```python
from cocotbext.ral import RuntimeRAL

# Enable with default filename
ral = RuntimeRAL("ip", model, txn_log=True)   # -> register_txns.log

# Enable with custom path
ral = RuntimeRAL("ip", model, txn_log="custom.log")

# Enable with file object
ral = RuntimeRAL("ip", model, txn_log=open("out.log", "w"))
```

### Log output format

```
--- TXN #001 @ 150.25us --------------------------------------------------------
  Operation  : WRITE
  Model Path : block.subsystem.CTRL
  Address    : 0x00000100
  Data       : 0xDEADBEEF
  Size       : 32-bit
  Protocol   : AXI
  Interface  : dut.axi_master
  Status     : OK
  Mirror     : 0x00000000 -> 0xDEADBEEF
  Fields:
    [31: 0] data             = 0xDEADBEEF  (was 0x0)
```

### Control methods

```python
ral.set_txn_phase("Phase 1: Reset check")   # annotate subsequent transactions
ral.write_txn_summary()                      # write summary block
ral.close_txn_log()                          # summary + close file
```

## Debug helpers

```python
# Dump all runtime state (addresses, field mirrored/desired/check values)
print(ral.dump_runtime_state())

# Compare expected vs actual for one register
print(ral.diff_runtime_state(actual=0xCAFEBABE, address=0x100))
```

## Volatile policy

```python
from cocotbext.ral.volatile_policy import is_field_volatile, check_allowed

# Check if a field is volatile
is_field_volatile(field)  # True for RO, RCLR, RSET (by default)

# Check if prediction checking is allowed
check_allowed(field, field_state)  # False if volatile or check_enabled=False
```

## Checker

Scoreboard for accumulating prediction results.

```python
from cocotbext.ral.checker import Checker

checker = Checker(name="my_ip")
checker.check(prediction_result)

print(checker.report())
assert not checker.has_errors()
checker.raise_on_errors()
```
