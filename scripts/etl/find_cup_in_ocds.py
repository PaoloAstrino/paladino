# Search for CUP with context
files_to_scan = ['data/anac/raw/ocds_2025_02.json']

def context_search(file_path):
    print(f'Context scan of {file_path} for "CUP"...')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                lines.append(line)
                if len(lines) > 20:
                    lines.pop(0)
                
                if 'CUP' in line.upper():
                    print(f'--- Match at line {i} ---')
                    for l in lines[-10:]:
                        print(l.strip())
                    # Also print next 5 lines
                    for _ in range(5):
                        try:
                            next_line = next(f)
                            print(next_line.strip())
                        except StopIteration:
                            break
                    print('------------------------')
                    break # Just find one good example
    except Exception as e:
        print(f'Error: {e}')

for f in files_to_scan:
    context_search(f)
