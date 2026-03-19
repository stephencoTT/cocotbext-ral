from cocotbext.ral.experimental import RuntimeRAL
from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess


# Build a simple model
model = RegisterModel("example")
reg = Register("CTRL", address=0x0, fields=[
    RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
    RegisterField("mode", lsb=1, msb=2, reset_value=0, sw_access=SwAccess.RW),
])
model.add_register(reg, "CTRL")

# Create runtime RAL
ral = RuntimeRAL("example", model)

# Predict a write
ral._predictor.predict_write(0x0, 0b101)

# Check a read
result = ral._predictor.predict_read(0x0, 0b101)

print("PASSED" if result.passed else "FAILED")

# Debug dump
print(ral.runtime_state)
