# coding: utf-8
import copy
from collections import defaultdict


L_PAREN = '('
R_PAREN = ')'
L_C_BRACE = '{'
R_C_BRACE = '}'
COMMA = ','
BAR = '|'
DOLLAR = '$'

WHITESPACE_RE = "^\s*"
PRED_NAME_RE = "^[\w_]*"
# Ex: $1, $4321
LAMBDA_ARG_RE = "^\$(?P<name>\d*)"
TYPED_LAMBDA_NAME_RE = "^(lambda|λ)\s*(?P<args>[$\w:\s,]*)\."
# Ex: $expandme123
NON_TERM_RE = "^\$(?P<name>[a-zA-Z]\w+)"
TEXT_FRAG_RE = "^['?!,.\w\s]*"
# Ex: {test} {test 1} {test?}
WILDCARD_RE = "^{(?P<inner>(?P<name>\w*)\s*(?P<type>(room|placement|beacon|male|female|known|alike|\d))?[\s{}\w]*(?P<obfuscated>\?)?)}"


WILDCARD_ALIASES = {"beacon": "location beacon",
"aobject": "object alike",
"female": "name female",
"kobject": "object known",
"male": "name male",
"placement": "location placement",
"room": "location room",
"sobject": "object special"}

class NonTerminal(object):
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return "NonTerminal({})".format(self.name)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, NonTerminal) and self.name == other.name


class WildCard(NonTerminal):
    """
    A nonterminal type representing some object, location, gesture, category, or name.
    Not fully modeled.
    """
    def __init__(self, name, obfuscated=False):
        self.obfuscated = obfuscated
        super(WildCard, self).__init__(name)
    def __str__(self):
        obfuscated_str = '?' if self.obfuscated else ""
        return "Wildcard({}{})".format(self.name, obfuscated_str)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, WildCard) and self.name == other.name and self.obfuscated == other.obfuscated


class TextFragment:
    """
    Represents a span of fully ground text.
    """
    def __init__(self, text):
        self.text = text.strip()
    def to_human_readable(self):
        return self.text
    def __str__(self):
        return "Frag({})".format(self.text)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, TextFragment) and self.text == other.text
    def __add__(self, other):
        assert isinstance(other, TextFragment)
        return TextFragment(self.text + " " + other.text)
    @staticmethod
    def join(fragments):
        if len(fragments) == 1:
            return fragments[0]
        return TextFragment(str.join(" ", [frag.text for frag in fragments]))


class String:
    def __init__(self, name):
        self.name = name
    def to_human_readable(self):
        return self.name
    def __str__(self):
        return "String({})".format(self.name)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, String) and self.name == other.name


class Constant(object):
    def __init__(self, name):
        self.name = name
    def to_human_readable(self):
        return self.name
    def __str__(self):
        return "{}".format(self.name)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, Constant) and self.name == other.name


class TemplateConstant(Constant):
    def __init__(self, name):
        super(TemplateConstant, self).__init__(name)
    def __eq__(self, other):
        return isinstance(other, TemplateConstant) and self.name == other.name


class Variable(object):
    def __init__(self, name):
        self.name = int(name)
    def to_human_readable(self):
        return str(self.name)
    def __str__(self):
        return "${}".format(self.name)
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, Variable) and self.name == other.name

class Predicate(object):
    """
    Logical predicate. Function applied to arguments that returns true or false.
    """
    def __init__(self, name, values):
        self.name = name
        self.values = values
    def __str__(self):
        arg_str = ""
        for value in self.values:
            arg_str += str(value) + " "
        return "( {} {} )".format(self.name, arg_str[:-1])
    def to_human_readable(self):
        arg_str = ""
        for value in self.values:
            arg_str += value.to_human_readable() + ", "
        return "{}({})".format(self.name, arg_str[:-2])
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, Predicate) and self.name == other.name and self.values == other.values


class TemplatePredicate(Predicate):
    """
    A predicate whose name is a placeholder
    """
    def __init__(self, name, values):
        super(TemplatePredicate, self).__init__(name, values)

    def __eq__(self, other):
        return isinstance(other, TemplatePredicate) and self.name == other.name and self.values == other.values


class Lambda:
    """
    A typed lambda
    Ex: lambda x:e(apple(x))
    Represents a function that finds some x that is an apple
    Ex: lambda x:e(and(apple(x),large(x)))
    Represents a function that finds some x that is a large apple
    """
    def __init__(self, name, types, body):
        self.name = name
        self.types = types
        self.body = body
    def to_human_readable(self):
        arg_string = ""
        for name, type in zip(self.name, self.types):
            arg_string += str(name) + ":" + type + ", "
        return "λ{}({})".format(arg_string[:-2], self.body.to_human_readable())
    def __str__(self):
        arg_string = ""
        for name, type in zip(self.name, self.types):
            arg_string += "$" + str(name) + " " + type + " "
        return "( λ {} {} )".format(arg_string[:-1], str(self.body))
    def __hash__(self):
        return hash(self.__str__())
    def __eq__(self, other):
        return isinstance(other, Predicate) and self.name == other.name and self.body == other.body


class SemanticTemplate(object):
    """
    A container for a semantic parse tree that keeps track of any
    nodes that are placeholders waiting for values.
    """
    def __init__(self, root):
        self.root = root
        self.unfilled_template_names = set()
        self._index_template_blanks_recursive(self.root)

    def _index_template_blanks_recursive(self, node):
        if isinstance(node, Lambda):
            self._index_template_blanks_recursive(node.body)
        elif isinstance(node, Predicate):
            if isinstance(node, TemplatePredicate):
                self.unfilled_template_names.add(node.name)
            for child in node.values:
                self._index_template_blanks_recursive(child)
        elif isinstance(node, TemplateConstant):
            self.unfilled_template_names.add(node.name)

    def fill_template(self, name, value):
        self.root = self._fill_template_recursive(self.root, name, value)
        self.unfilled_template_names.remove(name)

    def _fill_template_recursive(self, node, name, value):
        if isinstance(node, Lambda):
            node.body = self._fill_template_recursive(node.body, name, value)
            return node
        elif isinstance(node, Predicate):
            modified = node
            if isinstance(node, TemplatePredicate):
                if node.name == name:
                    modified = Predicate(value, node.values)
            for i, child in enumerate(modified.values):
                modified.values[i] = self._fill_template_recursive(child, name, value)
            return modified
        elif isinstance(node, TemplateConstant):
            if node.name == name:
                return Constant(value)
            else:
                return node
        else:
            return node

    def __str__(self):
        return str(self.root)

    def to_human_readable(self):
        return self.root.to_human_readable()


# The GPSR grammars all have this as their root
ROOT_SYMBOL = NonTerminal("Main")