# Code Coverage Improvement Strategy

## Current Status
- **Coverage**: 57.06% (349 passing tests)
- **Target**: 85%
- **Gap**: 27.94 percentage points
- **Statements to cover**: 343 out of 553 missed

## Module Analysis

### 1. app.py (54.8% coverage) - 434 lines missed
**Highest Priority - Biggest ROI**

#### Critical Uncovered Endpoints:
- **Lines 323-335, 343** (10 lines): Booking creation validation/error handling
- **Lines 375-380, 393-394** (9 lines): Booking status decision logic
- **Lines 454-455, 467** (3 lines): Notification triggering conditions
- **Lines 480-483, 495-498, 509-512** (12 lines): Message template error paths
- **Lines 642-679, 682-709** (60 lines): Customer sync operations (most complex)
- **Lines 726-742, 763-797** (50 lines): User management endpoints
- **Lines 817-913** (97 lines): **Reschedule endpoint** - HIGH IMPACT
- **Lines 934-950, 967-983** (40 lines): Maintenance reminder logic
- **Lines 1005-1006, 1039-1106** (65 lines): Settings/inbox endpoints
- **Lines 1183-1220, 1225-1240** (50 lines): Complex booking operations
- **Lines 1270-1335, 1350-1405** (120 lines): Error handling & edge cases

#### Strategy:
1. **Phase 1 (Easy wins - 5-8 points)**: Error paths in existing endpoints
2. **Phase 2 (Medium - 5-8 points)**: Reschedule workflow (lines 817-913)
3. **Phase 3 (Hard - 8-12 points)**: Customer sync logic (lines 642-709)
4. **Phase 4 (Complex - 10-15 points)**: Booking status transitions & notifications

### 2. whatsapp.py (47.0% coverage) - 106 lines missed
**Medium Priority**

#### Uncovered Functions:
- **Lines 31-40** (10 lines): Bridge discovery and profile loading
- **Lines 55-56** (2 lines): Contact fetching fallback
- **Lines 71, 73** (2 lines): Error handling in message sending
- **Lines 109-178** (70 lines): **Message parsing** - HIGH IMPACT
- **Lines 205-246** (42 lines): Contact data extraction
- **Lines 252, 255, 268-280** (12 lines): Edge cases in message handling

#### Strategy:
1. Mock external bridge API calls
2. Test message parsing edge cases
3. Test contact extraction with various formats
4. Test error conditions (network failures, invalid responses)

### 3. reminders.py (52.2% coverage) - 11 lines missed
**Low Priority - Easy wins**

#### Uncovered Code:
- **Lines 29-49** (21 lines): Reminder scheduling and due date checking

#### Strategy:
1. Create reminders at various time points (due, overdue, future)
2. Test run_due_reminders() with different time states
3. Test notification sending logic

---

## Implementation Roadmap

### Step 1: Fix Test Infrastructure (Current Blockers)
**Estimated gain**: 2-3%

1. **Clean up test database state**:
   ```python
   # Use transaction rollback in conftest.py
   @pytest.fixture
   def app_with_rollback(app):
       with app.app_context():
           transaction = db.session.begin_nested()
           yield app
           transaction.rollback()
   ```

2. **Fix duplicate constraint errors**: Create unique fixtures that don't collide
3. **Improve fixture isolation**: Each test gets fresh data

### Step 2: Target app.py Error Paths (5-8 points)
**Estimated: 50-70 new tests**

Focus on:
- Invalid booking dates
- Missing customer errors
- Conflict detection failures
- Message template rendering edge cases
- Phone number validation failures

```python
# Example tests needed:
test_booking_creation_invalid_date_range()
test_booking_creation_missing_service()
test_reschedule_past_date()
test_customer_duplicate_handling()
test_template_missing_placeholders()
```

### Step 3: Comprehensive Booking Workflows (8-12 points)
**Estimated: 40-60 new tests**

Full end-to-end workflows:
- Create → Confirm → Work → QC → Ready → Done
- Create → Reschedule → Confirm → Done
- Create → Cancel
- Multi-status transitions
- Concurrent booking conflicts

### Step 4: WhatsApp Service Integration (5-8 points)
**Estimated: 50-70 new tests**

1. **Message parsing edge cases**:
   - Various date formats (dd-mm-yyyy, yyyy-mm-dd, relative dates)
   - Phone number formats (08x, 628x, +628x, with dashes/spaces)
   - Package name variations (uppercase, lowercase, extra spaces)
   - Special characters, emoji, unicode

2. **Contact extraction**:
   - From phone number
   - From LID
   - From contact name
   - Data merging when same contact appears multiple ways

3. **Mock bridge API**:
   - Simulate bridge connection failures
   - Test contact fetch timeouts
   - Test message sending failures

### Step 5: Customer Operations (5-8 points)
**Estimated: 30-50 new tests**

Complex scenarios:
- Customer creation with various phone formats
- Customer update preserving existing data
- Merging customer data from multiple sources
- Vehicle info updates
- Multiple bookings per customer

### Step 6: Settings & Configuration (3-5 points)
**Estimated: 20-30 new tests**

- Save/load all setting types
- Reset to defaults
- Template variable substitution
- Missing settings handling

### Step 7: Maintenance Reminders (2-3 points)
**Estimated: 15-20 new tests**

- Create reminders at 6-month mark
- Send due reminders
- Track sent/review-requested states
- Handle multiple reminders per customer

---

## Quick Win Checklist

### Highest ROI (Do First)
- [ ] Test reschedule endpoint (lines 817-913): **+3-5 points**
- [ ] Test customer sync logic (lines 642-709): **+3-5 points**
- [ ] Test WhatsApp message parsing (lines 109-178): **+2-4 points**
- [ ] Test error paths in booking endpoints: **+2-3 points**

### Medium ROI
- [ ] Test all booking status transitions: **+2-3 points**
- [ ] Test settings save/load: **+1-2 points**
- [ ] Test maintenance reminders: **+1-2 points**

### Lower Priority
- [ ] Test edge cases in form parsing: **+1-2 points**
- [ ] Test phone number normalization: **+0.5-1 point**

---

## Testing Patterns

### For Endpoint Coverage:
```python
# GET endpoint flow
def test_endpoint_get(client, session_login, app):
    # Setup: Create test data in app context
    # Execute: GET request
    # Assert: Status code and response content

# POST endpoint flow  
def test_endpoint_post(client, session_login, app):
    # Setup: Create prerequisites
    # Execute: POST with valid/invalid data
    # Assert: Status code, redirect, or error message
    # Verify: Database changes made correctly
```

### For Service Functions:
```python
# Service function coverage
def test_service_function_nominal(app):
    with app.app_context():
        result = service_function(valid_input)
        assert result is not None
        
def test_service_function_error(app):
    with app.app_context():
        result = service_function(invalid_input)
        # Should handle gracefully (return None, empty, or raise)
```

---

## Timeline

- **Week 1**: Fix infrastructure + error paths (5-8%)
- **Week 2**: Booking workflows (8-12%)
- **Week 3**: WhatsApp services (5-8%)
- **Week 4**: Customer operations + settings (5-8%)
- **Week 5**: Maintenance reminders + polish (2-3%)

**Total expected**: 57% → **82-87%**

---

## Success Metrics

| Milestone | Coverage | Tests |
|-----------|----------|-------|
| Start | 57.06% | 349 |
| After Phase 1 | 60-62% | 380 |
| After Phase 2 | 65-68% | 450 |
| After Phase 3 | 70-73% | 520 |
| After Phase 4 | 75-78% | 600 |
| After Phase 5 | 80-82% | 650 |
| Final Polish | 85%+ | 700+ |

---

## Key Techniques

1. **Parameterized tests**: Test multiple inputs with one test function
2. **Fixtures**: Reusable test data (customers, bookings, services)
3. **Mocking**: Mock external APIs (bridge, contacts)
4. **Edge case matrix**: Test all combinations of statuses, roles, data states
5. **Error simulation**: Intentionally trigger error paths

---

## Potential Blockers & Solutions

| Issue | Solution |
|-------|----------|
| Database constraint errors | Use transaction rollback in fixtures |
| Complex workflow setup | Create factory functions for test data |
| Flaky tests | Explicit ordering, not depend on global state |
| Long test runs | Run selective suites, parallelize if needed |
| Mock complexity | Use simple mocks, focus on behavior not implementation |

