import os
import subprocess
import sys
from tempfile import NamedTemporaryFile

import teras


class Evaluator(teras.training.event.Listener):
    PERL = '/usr/bin/perl'
    SCRIPT = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), 'common', 'eval.pl')
    name = "evaluator"

    def __init__(self, parser, deprel_map, gold_file, logger=None, **kwargs):
        super().__init__(**kwargs)
        self._parser = parser
        self._deprel_map = deprel_map
        self._logger = logger \
            if logger is not None else teras.utils.logging.getLogger('teras')
        self.set_gold(gold_file)

    def set_gold(self, gold_file):
        self._gold_file = os.path.abspath(os.path.expanduser(gold_file))
        self.reset()

    def reset(self):
        self._parsed = {'sentences': [], 'heads': [], 'deprels': [],
                        'UAS': None, 'LAS': None}

    def append(self, sentences, parsed):
        self._parsed['sentences'].extend(sentences)
        heads, deprels = zip(*parsed)
        self._parsed['heads'].extend(heads)
        self._parsed['deprels'].extend(
            [self._deprel_map.lookup(d if d > 0 else 0) for d in deprel]
            for deprel in deprels)

    def report(self, show_details=False):
        with NamedTemporaryFile(mode='w') as f:
            write_conll(f, self._parsed['sentences'],
                        self._parsed['heads'], self._parsed['deprels'])
            result = exec_eval(f.name, self._gold_file, show_details)
            if result['code'] != 0:  # retry
                with NamedTemporaryFile(mode='w') as gold_f:
                    write_conll(gold_f, self._parsed['sentences'])
                    result = exec_eval(f.name, gold_f.name, show_details)
        if result['code'] == 0:
            self._parsed['UAS'] = result['UAS']
            self._parsed['LAS'] = result['LAS']
            message = "[evaluation]\n{}".format(result['raw'].rstrip())
        else:
            message = "[evaluation] ERROR({}): {}".format(
                result['code'], result['raw'].rstrip())
        self._logger.i(message)

    def on_batch_begin(self, data):
        pass

    def on_batch_end(self, data):
        if data['train']:
            return
        parsed = self._parser.parse(*data['xs'][:-1], use_cache=True)
        self.append([tokens[1:] for tokens in data['xs'][-1]], parsed)

    def on_epoch_validate_begin(self, data):
        self.reset()

    def on_epoch_validate_end(self, data):
        self.report(show_details=False)

    @property
    def result(self):
        return self._parsed


def write_conll(writer, sentences, heads=None, deprels=None):
    for i, tokens in enumerate(sentences):
        for j, token in enumerate(tokens):
            line = '\t'.join([
                str(token['id']),
                token['form'],
                token['lemma'],
                token['cpostag'],
                token['postag'],
                token['feats'],
                str(heads[i][j]) if heads is not None else str(token['head']),
                deprels[i][j] if deprels is not None else token['deprel'],
                token['phead'],
                token['pdeprel'],
            ])
            writer.write(line + '\n')
        writer.write('\n')
    writer.flush()


def exec_eval(parsed_file, gold_file, show_details=False):
    command = [Evaluator.PERL, Evaluator.SCRIPT,
               '-g', gold_file, '-s', parsed_file]
    if not show_details:
        command.append('-q')
    print("exec command: {}".format(' '.join(command)), file=sys.stderr)
    option = {}
    p = subprocess.run(command,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,
                       **option)
    output = (p.stdout if p.returncode == 0 else p.stderr).decode('utf-8')
    result = {
        'code': p.returncode,
        'raw': output,
        'UAS': None,
        'LAS': None,
    }
    if p.returncode == 0:
        lines = output.split('\n', 2)[:2]
        result['LAS'], result['UAS'] = \
            [float(line.rsplit(' ', 2)[-2]) for line in lines]
    return result
