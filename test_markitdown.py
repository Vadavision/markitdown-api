from markitdown import MarkItDown

# Initialize MarkItDown
md = MarkItDown()

# Test with a simple text file
result = md.convert("test-document.txt")

# Print the result
print("Conversion result:")
print(result.text_content)
print("\nMetadata:")
print(result.metadata)
