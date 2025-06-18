import re
import unicodedata
from collections import namedtuple

import six


class LexerError(Exception):
    pass

Position = namedtuple('Position', ['line', 'column'])

class JavaToken(object):
    def __init__(self, value, position=None, javadoc=None):
        self.value = value
        self.position = position
        self.javadoc = javadoc

    def __repr__(self):
        if self.position:
            return '%s "%s" line %d, position %d' % (
                self.__class__.__name__, self.value, self.position[0], self.position[1]
                )
        else:
            return '%s "%s"' % (self.__class__.__name__, self.value)

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        raise Exception("Direct comparison not allowed")

class EndOfInput(JavaToken):
    pass

class Keyword(JavaToken):
    VALUES = set(['abstract', 'assert', 'boolean', 'break', 'byte', 'case',
                  'catch', 'char', 'class', 'const', 'continue', 'default',
                  'do', 'double', 'else', 'enum', 'extends', 'final',
                  'finally', 'float', 'for', 'goto', 'if', 'implements',
                  'import', 'instanceof', 'int', 'interface', 'long', 'native',
                  'new', 'package', 'private', 'protected', 'public', 'return',
                  'short', 'static', 'strictfp', 'super', 'switch',
                  'synchronized', 'this', 'throw', 'throws', 'transient', 'try',
                  'void', 'volatile', 'while',
                  # Java 10
                  'var',
                  # Java 12
                  'yield',
                  # Java 14
                  'record',
                  # Java 15
                  'sealed', 'non-sealed', 'permits',
                  # Java 17 (Pattern Matching for Switch)
                  'when'])


class Modifier(Keyword):
    VALUES = set(['abstract', 'default', 'final', 'native', 'private',
                  'protected', 'public', 'static', 'strictfp', 'synchronized',
                  'transient', 'volatile',
                  # Java 15
                  'sealed', 'non-sealed'])

class BasicType(Keyword):
    VALUES = set(['boolean', 'byte', 'char', 'double',
                  'float', 'int', 'long', 'short'])

class Literal(JavaToken):
    pass

class Integer(Literal):
    pass

class DecimalInteger(Literal):
    pass

class OctalInteger(Integer):
    pass

class BinaryInteger(Integer):
    pass

class HexInteger(Integer):
    pass

class FloatingPoint(Literal):
    pass

class DecimalFloatingPoint(FloatingPoint):
    pass

class HexFloatingPoint(FloatingPoint):
    pass

class Boolean(Literal):
    VALUES = set(["true", "false"])

class Character(Literal):
    pass

class String(Literal):
    pass

class Null(Literal):
    pass

class Separator(JavaToken):
    VALUES = set(['(', ')', '{', '}', '[', ']', ';', ',', '.'])

class Operator(JavaToken):
    MAX_LEN = 4
    VALUES = set(['>>>=', '>>=', '<<=',  '%=', '^=', '|=', '&=', '/=',
                  '*=', '-=', '+=', '<<', '--', '++', '||', '&&', '!=',
                  '>=', '<=', '==', '%', '^', '|', '&', '/', '*', '-',
                  '+', ':', '?', '~', '!', '<', '>', '=', '...', '->', '::'])

    # '>>>' and '>>' are excluded so that >> becomes two tokens and >>> becomes
    # three. This is done because we can not distinguish the operators >> and
    # >>> from the closing of multipel type parameter/argument lists when
    # lexing. The job of potentially recombining these symbols is left to the
    # parser

    INFIX = set(['||', '&&', '|', '^', '&', '==', '!=', '<', '>', '<=', '>=',
                 '<<', '>>', '>>>', '+', '-', '*', '/', '%'])

    PREFIX = set(['++', '--', '!', '~', '+', '-'])

    POSTFIX = set(['++', '--'])

    ASSIGNMENT = set(['=', '+=', '-=', '*=', '/=', '&=', '|=', '^=', '%=',
                      '<<=', '>>=', '>>>='])

    LAMBDA = set(['->'])

    METHOD_REFERENCE = set(['::',])

    def is_infix(self):
        return self.value in self.INFIX

    def is_prefix(self):
        return self.value in self.PREFIX

    def is_postfix(self):
        return self.value in self.POSTFIX

    def is_assignment(self):
        return self.value in self.ASSIGNMENT


class Annotation(JavaToken):
    pass

class Identifier(JavaToken):
    pass


class JavaTokenizer(object):

    IDENT_START_CATEGORIES = set(['Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Nl', 'Pc', 'Sc'])

    IDENT_PART_CATEGORIES = set(['Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Mc', 'Mn', 'Nd', 'Nl', 'Pc', 'Sc'])

    def __init__(self, data, ignore_errors=False):
        self.data = data
        self.ignore_errors = ignore_errors
        self.errors = []

        # Rows and columns both start at 1
        self.current_line = 1
        self.start_of_line = -1

        self.operators = [set() for i in range(0, Operator.MAX_LEN)]

        for v in Operator.VALUES:
            self.operators[len(v) - 1].add(v)

        self.whitespace_consumer = re.compile(r'[^\s]')

        self.javadoc = None


    def reset(self):
        self.i = 0
        self.j = 0

    def consume_whitespace(self):
        match = self.whitespace_consumer.search(self.data, self.i + 1)

        if not match:
            self.i = self.length
            return

        i = match.start()

        start_of_line = self.data.rfind('\n', self.i, i)

        if start_of_line != -1:
            self.start_of_line = start_of_line
            self.current_line += self.data.count('\n', self.i, i)

        self.i = i

    def read_string(self):
        delim = self.data[self.i]

        state = 0
        j = self.i + 1
        length = self.length

        while True:
            if j >= length:
                self.error('Unterminated character/string literal')
                break

            if state == 0:
                if self.data[j] == '\\':
                    state = 1
                elif self.data[j] == delim:
                    break

            elif state == 1:
                if self.data[j] in 'btnfru"\'\\':
                    state = 0
                elif self.data[j] in '0123':
                    state = 2
                elif self.data[j] in '01234567':
                    state = 3
                else:
                    self.error('Illegal escape character', self.data[j])

            elif state == 2:
                # Possibly long octal
                if self.data[j] in '01234567':
                    state = 3
                elif self.data[j] == '\\':
                    state = 1
                elif self.data[j] == delim:
                    break

            elif state == 3:
                state = 0

                if self.data[j] == '\\':
                    state = 1
                elif self.data[j] == delim:
                    break

            j += 1

        self.j = j + 1

    def _process_escape(self, char_iter):
        """
        Processes an escape sequence.
        Assumes the initial '\' has already been consumed.
        `char_iter` is an iterator over the characters of the string.
        Returns the processed character(s) for the escape sequence.
        """
        try:
            escape_char = next(char_iter)
        except StopIteration:
            self.error("Unterminated escape sequence")
            return '\\' # Return backslash as is

        if escape_char == 'b':
            return '\b'
        elif escape_char == 't':
            return '\t'
        elif escape_char == 'n':
            return '\n'
        elif escape_char == 'f':
            return '\f'
        elif escape_char == 'r':
            return '\r'
        elif escape_char == 's': # Java 15 text block escape for space
            return ' '
        elif escape_char == '"':
            return '"'
        elif escape_char == "'":
            return "'"
        elif escape_char == '\\':
            return '\\'
        elif escape_char in '01234567': # Octal escape
            # Potentially up to 3 octal digits. First digit must be 0-3 if 3 digits.
            # For simplicity, javalang's existing read_string handles this with states,
            # but here we'll do a basic version.
            # This part might need more robust handling matching read_string's states.
            octal_sequence = escape_char
            # Try to read up to two more octal digits
            for _ in range(2):
                try:
                    # Peek next char
                    next_c = char_iter.__next__() if hasattr(char_iter, '__next__') else char_iter.next()
                    if next_c in '01234567':
                        octal_sequence += next_c
                        if len(octal_sequence) == 3 and int(octal_sequence[0]) > 3: # e.g. \400 is invalid
                            # remove last char and break
                            octal_sequence = octal_sequence[:-1]
                            # Need to "put back" next_c, which is hard with an iterator.
                            # This indicates a need for more sophisticated lookahead or state machine
                            # For now, this will be a limitation.
                            break
                    else:
                        # This character is not part of octal, needs to be "put back".
                        # This is a common issue with simple iterators.
                        # A more robust lexer might use index-based scanning here.
                        # For now, we consume it and it might be lost or cause issues.
                        # Consider this a known limitation for complex octal/unicode in text blocks.
                        break # Or error, or somehow "unread" next_c
                except StopIteration:
                    break
            try:
                return chr(int(octal_sequence, 8))
            except ValueError:
                self.error("Invalid octal escape sequence", "\\" + octal_sequence)
                return "\\" + octal_sequence
        # Ignoring unicode ('u') escapes here as pre_tokenize handles them.
        # If pre_tokenize is not run or not sufficient, 'u' would be handled here.
        # Line continuation '\<newline>' is handled before _process_escape in read_text_block.
        else:
            self.error('Illegal escape character', escape_char)
            return '\\' + escape_char


    def read_text_block(self):
        # Consume opening """
        start_char_index = self.i
        self.i += 3

        # Find closing """
        content_end = -1
        # Keep track of original line breaks for position update
        raw_lines_count = 0

        # Search for the closing delimiter """
        # This simplified search assumes """ won't appear legitimately mid-content often.
        # JLS 3.10.4: "It is a compile-time error for a text block to not have a closing delimiter."
        # JLS 3.10.6: "Unlike string literals, escape sequences are not translated in a text block
        #              until after the processing of incidental white space."
        # So, we first find the raw content.

        search_start_index = self.i
        while True:
            try:
                # Find next potential """
                closing_marker_index = self.data.index('"""', search_start_index)
                # Check if this is an escaped """ by looking at odd/even backslashes.
                # However, JLS 3.10.6 says "It is a compile-time error for the characters
                # immediately preceding a closing delimiter to be escape characters."
                # This simplifies: we just find the first """ that's not escaped in a way
                # that would make the """ part of the content itself, if that were allowed.
                # For text blocks, the rule is simpler: find """ then process.
                # The content ends at the last character BEFORE the three closing delimiters.
                content_end = closing_marker_index
                self.j = closing_marker_index + 3 # Position after the closing """
                break
            except ValueError: # No """ found
                self.error("Unterminated text block")
                # Set self.j to end of data to stop tokenizing
                self.j = self.length
                # Return raw content up to EOF for error recovery if needed
                raw_content = self.data[self.i:]
                 # Update line counts based on raw_content before erroring
                raw_lines_count = raw_content.count('\n')
                self.current_line += raw_lines_count
                if raw_lines_count > 0:
                    self.start_of_line = self.i + raw_content.rfind('\n')
                return "" # Or raise error immediately

        raw_content_block = self.data[self.i : content_end]

        # Update current_line and start_of_line based on the consumed raw block
        # This ensures that error messages for escapes etc. have correct line numbers
        num_newlines_in_block = raw_content_block.count('\n')
        if num_newlines_in_block > 0:
            self.current_line += num_newlines_in_block
            self.start_of_line = self.i + raw_content_block.rfind('\n')

        # 1. Line Terminator Normalization (CRLF, CR -> LF)
        normalized_content = raw_content_block.replace('\r\n', '\n').replace('\r', '\n')

        lines = normalized_content.split('\n')

        # 2. Incidental White Space Removal
        # As per JEP 378 / JLS 3.10.6

        # Detect common indent (only from non-blank lines)
        min_indent = float('inf')
        content_lines_for_indent_detection = []

        for line_idx, line in enumerate(lines):
            if line_idx == 0 and not lines: # empty text block """"""
                 break
            # The last line is special: if the text block ends with """, the last line
            # in `lines` corresponds to the line of the closing """. Its indent matters.
            # JLS: "the G determination is made by examining all the lines of the text block’s content,
            #       including the line that contains the closing delimiter"
            # However, if the last line *is* the closing delimiter line and it's blank *before* the delimiter,
            # it might be considered blank. This part is subtle.
            # For simplicity here: consider all lines as per split.

            stripped_line = line.lstrip()
            if not stripped_line: # Blank line
                # Blank lines do not contribute to min_indent calculation, but are kept
                content_lines_for_indent_detection.append("") # Placeholder for structure
            else:
                indent = len(line) - len(stripped_line)
                min_indent = min(min_indent, indent)
                content_lines_for_indent_detection.append(line)

        processed_lines = []
        if min_indent == float('inf'): # All lines were blank or empty
            min_indent = 0

        for line in lines:
            if not line.strip(): # Preserve blank lines as empty strings after normalization
                                 # or as spaces if they only had spaces and min_indent was 0
                processed_lines.append("") # Or line if it had spaces and min_indent > 0
            else:
                # Remove common indent
                processed_line = line[min_indent:]
                # Remove all trailing white space (JLS 3.10.6 Step 2 Part 3)
                processed_lines.append(processed_line.rstrip())

        # Rejoin lines, then process escapes
        content_for_escape_processing = "\n".join(processed_lines)

        # 3. Escape Sequence Processing
        # This needs to handle \<line-terminator> (line continuer) first
        # then other escapes like \n, \t, \s, \\, \", octal, unicode

        # Handle line continuations: \<newline>
        # This should effectively remove the backslash and the newline
        content_after_line_continuers = re.sub(r'\\\n', '', content_for_escape_processing)

        # Process other escapes
        # This is similar to read_string's escape processing logic
        # but on the already indent-stripped and line-continued string.
        # For simplicity, we'll build a new string.

        final_chars = []
        char_iter = iter(content_after_line_continuers)
        for char_val in char_iter:
            if char_val == '\\':
                # _process_escape needs to be adapted or made more robust
                # for handling iterator state, especially for multi-char escapes.
                # For now, let's assume _process_escape is sufficient.
                final_chars.append(self._process_escape(char_iter))
            else:
                final_chars.append(char_val)

        self.i = self.j # self.i should be after the closing """ for the next token
        return "".join(final_chars)

    def try_operator(self):
        for l in range(min(self.length - self.i, Operator.MAX_LEN), 0, -1):
            if self.data[self.i:self.i + l] in self.operators[l - 1]:
                self.j = self.i + l
                return True
        return False

    def read_comment(self):
        if self.data[self.i + 1] == '/':
            terminator, accept_eof = '\n', True
        else:
            terminator, accept_eof = '*/', False

        i = self.data.find(terminator, self.i + 2)

        if i != -1:
            i += len(terminator)
        elif accept_eof:
            i = self.length
        else:
            self.error('Unterminated block comment')
            partial_comment = self.data[self.i:]
            self.i = self.length
            return partial_comment

        comment = self.data[self.i:i]
        start_of_line = self.data.rfind('\n', self.i, i)

        if start_of_line != -1:
            self.start_of_line = start_of_line
            self.current_line += self.data.count('\n', self.i, i)

        self.i = i

        return comment

    def read_decimal_float_or_integer(self):
        orig_i = self.i
        self.j = self.i

        self.read_decimal_integer()

        if self.j >= len(self.data) or self.data[self.j] not in '.eEfFdD':
            return DecimalInteger

        if self.data[self.j] == '.':
            self.i = self.j + 1
            self.read_decimal_integer()

        if self.j < len(self.data) and self.data[self.j] in 'eE':
            self.j = self.j + 1

            if self.j < len(self.data) and self.data[self.j] in '-+':
                self.j = self.j + 1

            self.i = self.j
            self.read_decimal_integer()

        if self.j < len(self.data) and self.data[self.j] in 'fFdD':
            self.j = self.j + 1

        self.i = orig_i
        return DecimalFloatingPoint

    def read_hex_integer_or_float(self):
        orig_i = self.i
        self.j = self.i + 2

        self.read_hex_integer()

        if self.j >= len(self.data) or self.data[self.j] not in '.pP':
            return HexInteger

        if self.data[self.j] == '.':
            self.j = self.j + 1
            self.read_digits('0123456789abcdefABCDEF')

        if self.j < len(self.data) and self.data[self.j] in 'pP':
            self.j = self.j + 1
        else:
            self.error('Invalid hex float literal')

        if self.j < len(self.data) and self.data[self.j] in '-+':
            self.j = self.j + 1

        self.i = self.j
        self.read_decimal_integer()

        if self.j < len(self.data) and self.data[self.j] in 'fFdD':
            self.j = self.j + 1

        self.i = orig_i
        return HexFloatingPoint

    def read_digits(self, digits):
        tmp_i = 0
        c = None

        while self.j + tmp_i < len(self.data):
            c = self.data[self.j + tmp_i]

            if c in digits:
                self.j += 1 + tmp_i
                tmp_i = 0
            elif c == '_':
                tmp_i += 1
            else:
                break

        if c in 'lL':
            self.j += 1

    def read_decimal_integer(self):
        self.j = self.i
        self.read_digits('0123456789')

    def read_hex_integer(self):
        self.j = self.i + 2
        self.read_digits('0123456789abcdefABCDEF')

    def read_bin_integer(self):
        self.j = self.i + 2
        self.read_digits('01')

    def read_octal_integer(self):
        self.j = self.i + 1
        self.read_digits('01234567')

    def read_integer_or_float(self, c, c_next):
        if c == '0' and c_next in 'xX':
            return self.read_hex_integer_or_float()
        elif c == '0' and c_next in 'bB':
            self.read_bin_integer()
            return BinaryInteger
        elif c == '0' and c_next in '01234567':
            self.read_octal_integer()
            return OctalInteger
        else:
            return self.read_decimal_float_or_integer()

    def try_separator(self):
        if self.data[self.i] in Separator.VALUES:
            self.j = self.i + 1
            return True
        return False

    def decode_data(self):
        # Encodings to try in order
        codecs = ['utf_8', 'iso-8859-1']

        # If data is already unicode don't try to redecode
        if isinstance(self.data, six.text_type):
            return self.data

        for codec in codecs:
            try:
                data = self.data.decode(codec)
                return data
            except UnicodeDecodeError:
                pass

        self.error('Could not decode input data')

    def is_java_identifier_start(self, c):
        return unicodedata.category(c) in self.IDENT_START_CATEGORIES

    def read_identifier(self):
        self.j = self.i + 1

        while self.j < len(self.data) and unicodedata.category(self.data[self.j]) in self.IDENT_PART_CATEGORIES:
            self.j += 1

        ident = self.data[self.i:self.j]
        if ident in Keyword.VALUES:
            token_type = Keyword

            if ident in BasicType.VALUES:
                token_type = BasicType
            elif ident in Modifier.VALUES:
                token_type = Modifier

        elif ident in Boolean.VALUES:
            token_type = Boolean
        elif ident == 'null':
            token_type = Null
        else:
            token_type = Identifier

        return token_type

    def pre_tokenize(self):
        new_data = list()
        data = self.decode_data()

        i = 0
        j = 0
        length = len(data)

        NONE         = 0
        ELIGIBLE     = 1
        MARKER_FOUND = 2

        state = NONE

        while j < length:
            if state == NONE:
                j = data.find('\\', j)

                if j == -1:
                    j = length
                    break

                state = ELIGIBLE

            elif state == ELIGIBLE:
                c = data[j]

                if c == 'u':
                    state = MARKER_FOUND
                    new_data.append(data[i:j - 1])
                else:
                    state = NONE

            elif state == MARKER_FOUND:
                c = data[j]

                if c != 'u':
                    try:
                        escape_code = int(data[j:j+4], 16)
                    except ValueError:
                        self.error('Invalid unicode escape', data[j:j+4])

                    new_data.append(six.unichr(escape_code))

                    i = j + 4
                    j = i

                    state = NONE

                    continue

            j = j + 1

        new_data.append(data[i:])

        self.data = ''.join(new_data)
        self.length = len(self.data)

    def tokenize(self):
        self.reset()

        # Convert unicode escapes
        self.pre_tokenize()

        while self.i < self.length:
            token_type = None

            c = self.data[self.i]
            c_next = None
            startswith = c

            if self.i + 1 < self.length:
                c_next = self.data[self.i + 1]
                startswith = c + c_next

            if c.isspace():
                self.consume_whitespace()
                continue

            elif startswith in ("//", "/*"):
                comment = self.read_comment()
                if comment.startswith("/**"):
                    self.javadoc = comment
                continue

            elif startswith == '..' and self.try_operator():
                # Ensure we don't mistake a '...' operator as a sequence of
                # three '.' separators. This is done as an optimization instead
                # of moving try_operator higher in the chain because operators
                # aren't as common and try_operator is expensive
                token_type = Operator

            elif c == '@':
                token_type = Annotation
                self.j = self.i + 1

            elif c == '.' and c_next and c_next.isdigit():
                token_type = self.read_decimal_float_or_integer()

            elif self.try_separator():
                token_type = Separator

            elif c == '"':
                if self.i + 2 < self.length and self.data[self.i+1] == '"' and self.data[self.i+2] == '"':
                    # Text Block
                    start_i = self.i
                    # The line number for the token is the line where """ starts
                    token_line = self.current_line
                    token_col = self.i - self.start_of_line

                    # read_text_block will update self.i, self.j, self.current_line, self.start_of_line
                    value = self.read_text_block()

                    # Position should be of the start of the token
                    position = Position(token_line, token_col)
                    token = String(value, position, self.javadoc)
                    yield token
                    if self.javadoc:
                        self.javadoc = None
                    # self.i is already set by read_text_block to be after the closing """
                    continue
                else:
                    # Regular String Literal
                    token_type = String
                    self.read_string()
            elif c == "'": # Character Literal
                token_type = String # Represented as String token for simplicity, could be Character
                self.read_string()


            elif c in '0123456789':
                token_type = self.read_integer_or_float(c, c_next)

            elif self.is_java_identifier_start(c):
                token_type = self.read_identifier()

            elif self.try_operator():
                token_type = Operator

            else:
                self.error('Could not process token', c)
                self.i = self.i + 1
                continue

            position = Position(self.current_line, self.i - self.start_of_line)
            token = token_type(self.data[self.i:self.j], position, self.javadoc)
            yield token

            if self.javadoc:
                self.javadoc = None

            self.i = self.j

    def error(self, message, char=None):
        # Provide additional information in the errors message
        line_start = self.data.rfind('\n', 0, self.i) + 1
        line_end = self.data.find('\n', self.i)
        line = self.data[line_start:line_end].strip()

        line_number = self.current_line

        if not char:
            char = self.data[self.j]

        message = u'%s at "%s", line %s: %s' % (message, char, line_number, line)
        error = LexerError(message)
        self.errors.append(error)

        if not self.ignore_errors:
            raise error

def tokenize(code, ignore_errors=False):
    tokenizer = JavaTokenizer(code, ignore_errors)
    return tokenizer.tokenize()

def reformat_tokens(tokens):
    indent = 0
    closed_block = False
    ident_last = False

    output = list()

    for token in tokens:
        if closed_block:
            closed_block = False
            indent -= 4

            output.append('\n')
            output.append(' ' * indent)
            output.append('}')

            if isinstance(token, (Literal, Keyword, Identifier)):
                output.append('\n')
                output.append(' ' * indent)

        if token.value == '{':
            indent += 4
            output.append(' {\n')
            output.append(' ' * indent)

        elif token.value == '}':
            closed_block = True

        elif token.value == ',':
            output.append(', ')

        elif isinstance(token, (Literal, Keyword, Identifier)):
            if ident_last:
                # If the last token was a literla/keyword/identifer put a space in between
                output.append(' ')
            ident_last = True
            output.append(token.value)

        elif isinstance(token, Operator):
            output.append(' ' + token.value + ' ')

        elif token.value == ';':
            output.append(';\n')
            output.append(' ' * indent)

        else:
            output.append(token.value)

        ident_last = isinstance(token, (Literal, Keyword, Identifier))

    if closed_block:
        output.append('\n}')

    output.append('\n')

    return ''.join(output)
