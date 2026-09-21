# Define idempotency and uncertain-write recovery

Type: grilling
Status: open
Blocked by: 04

## Question

How does the execution invocation distinguish an existing exact-name task, a newly created task, and a timed-out write whose server result is uncertain, without creating duplicates or accepting a similar historical task?
