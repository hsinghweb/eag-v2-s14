# TypeError Fix for Data Extraction

## Problem
The system encountered `TypeError: string indices must be integers, not 'str'` during data extraction from real estate websites. This error occurs when code tries to access a string as if it were a dictionary or list.

## Root Cause
- Tools may return strings (error messages, JSON strings, or plain text) instead of expected dictionaries/lists
- Code assumes tool results are dictionaries and tries to access them with `result['key']`
- When `result` is actually a string, Python raises `TypeError`

## Solution Implemented

### 1. Enhanced TypeError Handling in Executor
**File**: `action/executor.py`

Added specific `TypeError` exception handler that:
- Detects "string indices must be integers" errors
- Provides actionable guidance on type checking
- Suggests safe access patterns
- Includes code examples for proper validation

**Error Message Example**:
```
TypeError: Trying to access a string as if it were a dictionary or list.

💡 Fix strategies:
  - Always check the type before accessing: `if isinstance(result, dict):`
  - Check for error messages: `if isinstance(result, str) and result.startswith('[error]'):`
  - Validate tool results: `if result and isinstance(result, (dict, list)):`
  - Handle string results: `if isinstance(result, str): result = json.loads(result)`
```

### 2. Enhanced Agent Guidance
**File**: `prompts/decision_prompt.txt`

Added comprehensive guidance on:
- **Type checking before access**: Always verify `isinstance(result, dict)` before `result['key']`
- **Safe access patterns**: Examples of proper validation
- **JSON string handling**: How to parse JSON strings returned by tools
- **Error message detection**: Check for `[error]` prefixes

**Key Guidance Added**:
```python
# WRONG - will cause TypeError if result is a string:
value = result['key']  # ❌ TypeError if result is string

# CORRECT - check type first:
if isinstance(result, dict) and 'key' in result:
    value = result['key']  # ✅ Safe
elif isinstance(result, str):
    # Handle string result (might be error or JSON)
    if result.startswith('[error]'):
        return { "error_0A": result }
    else:
        try:
            result = json.loads(result)  # Try parsing JSON
            value = result.get('key')
        except:
            return { "error_0A": "Failed to parse result" }
```

### 3. Data Extraction Best Practices
Added specific guidance for real estate data extraction:
- Extract content first: `get_comprehensive_markdown()`
- Check type before parsing
- Use regex patterns for text extraction
- Handle unexpected types gracefully

## Common Scenarios

### Scenario 1: Tool Returns Error String
```python
# Tool returns: "[error] Connection failed"
result = tool_call()
# ❌ WRONG:
price = result['price']  # TypeError!

# ✅ CORRECT:
if isinstance(result, str) and result.startswith('[error]'):
    return { "error_0A": result }
elif isinstance(result, dict):
    price = result.get('price')
```

### Scenario 2: Tool Returns JSON String
```python
# Tool returns: '{"price": 20000, "bhk": 2}'
result = tool_call()
# ❌ WRONG:
price = result['price']  # TypeError!

# ✅ CORRECT:
if isinstance(result, str):
    try:
        result = json.loads(result)
        price = result.get('price')
    except:
        return { "error_0A": "Failed to parse JSON" }
elif isinstance(result, dict):
    price = result.get('price')
```

### Scenario 3: Extracting from Page Content
```python
# Extract page content
content = get_comprehensive_markdown()

# ✅ SAFE: Check type and parse
if isinstance(content, str):
    import re
    prices = re.findall(r'₹[\d,]+', content)
    return { "prices_0A": prices }
elif isinstance(content, dict):
    if 'prices' in content:
        return { "prices_0A": content['prices'] }
else:
    return { "error_0A": f"Unexpected type: {type(content)}" }
```

## Prevention Checklist

Before accessing tool results:
- [ ] Check if result is `None`: `if result is None:`
- [ ] Check result type: `isinstance(result, dict)` or `isinstance(result, list)`
- [ ] Check for error strings: `if isinstance(result, str) and result.startswith('[error]'):`
- [ ] Use safe access: `result.get('key')` instead of `result['key']`
- [ ] Handle JSON strings: `json.loads(result)` if `isinstance(result, str)`
- [ ] Provide fallback: Return error message if type is unexpected

## Expected Improvements

- ✅ **Clearer error messages**: Specific guidance for TypeError
- ✅ **Better agent behavior**: Agent will check types before accessing
- ✅ **Fewer crashes**: Graceful handling of unexpected result types
- ✅ **Better data extraction**: Proper parsing of strings vs dicts

## Testing

To verify the fix works:
1. Test with tool that returns error string
2. Test with tool that returns JSON string
3. Test with tool that returns dict
4. Verify error messages are helpful
5. Verify agent recovers gracefully

