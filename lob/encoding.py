import numpy as np
import pandas as pd
import jax
import jax.numpy as jnp
from functools import partial


NA_VAL = -9999
HIDDEN_VAL = -20000
MASK_VAL = -10000


@jax.jit
def encode(ar, ks, vs):
    """ replace values in ar with values in vs at indices in ks 
        (mapping from vs to ks)
    """
    return vs[jnp.searchsorted(ks, ar)]

@jax.jit
def decode(ar, ks, vs):
    return encode(ar, vs, ks)

@jax.jit
def is_special_val(x):
    return jnp.isin(x, jnp.array([MASK_VAL, HIDDEN_VAL, NA_VAL])).any()

#@partial(jax.jit, static_argnums=(1,))
def expand_special_val(x, n_tokens):
    # val = encode(
    #     x,
    #     jnp.array([MASK_VAL, HIDDEN_VAL, NA_VAL]),
    #     jnp.array([Vocab.MASK_TOK, Vocab.HIDDEN_TOK, Vocab.NA_TOK])
    # )
    return jnp.tile(x, (n_tokens,))

@partial(jax.jit, static_argnums=(1,2,3))
#@partial(jax.vmap, in_axes=(0, None, None, None))
def split_int(x, n_tokens, tok_len, prepend_sign_token=False):

    if prepend_sign_token:
        sign = jnp.sign(x)
        # only allow pos or neg sign, counting zero as negative (-0)
        sign = jnp.where(sign == 0, -1, sign)
    
    x = jnp.abs(x)
    base = 10
    #n_digits = jnp.floor(jnp.max(jnp.log(x) / jnp.log(base)) + 1).astype(int)
    n_digits = n_tokens * tok_len
    div_exp = jnp.flip(
        jnp.arange(0, n_digits, tok_len))
    splits = (x // (base ** div_exp)) % (10**tok_len)
    if prepend_sign_token:
        splits = jnp.hstack([sign, splits])
    return splits

@partial(jax.jit, static_argnums=(1,))
def combine_int(x, tok_len, sign=1):
    base = 10
    n_digits = jnp.expand_dims(x, axis=0).shape[-1] * tok_len
    exp = jnp.flip(
        jnp.arange(0, n_digits, tok_len))
    return sign * jnp.sum(x * (base ** exp), axis=-1)

@partial(jax.jit, static_argnums=(1,2,3))
def split_field(x, n_tokens, tok_len, prepend_sign_token=False):
    total_tokens = n_tokens + int(prepend_sign_token)
    return jax.lax.cond(
        is_special_val(x),
        lambda arg: expand_special_val(arg, total_tokens),
        lambda arg: split_int(arg, n_tokens, tok_len, prepend_sign_token),
        x)

@partial(jax.jit, static_argnums=(1,))
def combine_field(x, tok_len, sign=1):
    return jax.lax.cond(
        is_special_val(x),
        lambda arg: NA_VAL,
        lambda arg: combine_int(arg, tok_len, sign),
        x)

# event_type	direction	price	size	delta_t	time_s	time_ns	price_ref	size_ref	time_s_ref	time_ns_ref
@jax.jit
def encode_msg(msg, encoding):
    event_type = encode(msg[0], *encoding['event_type'])
    
    direction = encode(msg[1], *encoding['direction'])
    
    price = split_field(msg[2], 1, 3, True)
    price_sign = encode(price[0], *encoding['sign'])
    price = encode(price[1], *encoding['price'])
    
    size = encode(msg[3], *encoding['size'])
    
    delta_t_s = msg[4]
    # delta_t = encode(delta_t, *encoding['time'])
    delta_t_ns = split_field(msg[5], 3, 3, False)
    
    time_s = split_field(msg[6], 2, 3, False)
    # time_s = encode(time_s, *encoding['time'])
    
    time_ns = split_field(msg[7], 3, 3, False)
    # time_ns = encode(time_ns, *encoding['time'])
    #time_comb = split_field(msg[4:8], 9, 3, False)
    time_comb = jnp.hstack([delta_t_s, delta_t_ns, time_s, time_ns])
    time_comb = encode(time_comb, *encoding['time'])

    price_ref = split_field(msg[8], 1, 3, True)
    price_ref_sign = encode(price_ref[0], *encoding['sign'])
    price_ref = encode(price_ref[1], *encoding['price'])

    size_ref = encode(msg[9], *encoding['size'])

    time_s_ref = split_field(msg[10], 2, 3, False)
    #time_s_ref = encode(time_s_ref, *encoding['time'])

    time_ns_ref = split_field(msg[11], 3, 3, False)
    #time_ns_ref = encode(time_ns_ref, *encoding['time'])
    time_ref_comb = jnp.hstack([time_s_ref, time_ns_ref])
    time_ref_comb = encode(time_ref_comb, *encoding['time'])

    out = [
        event_type, direction, price_sign, price, size, time_comb, # delta_t, time_s, time_ns,
        price_ref_sign, price_ref, size_ref, time_ref_comb]
    return jnp.hstack(out[:msg.shape[0]]) # time_s_ref, time_ns_ref])
    

encode_msgs = jax.jit(jax.vmap(encode_msg, in_axes=(0,)))

@jax.jit
def decode_msg(msg_enc, encoding):
    event_type = encode(msg_enc[0], *encoding['event_type'][::-1])
    
    direction = encode(msg_enc[1], *encoding['direction'][::-1])

    price_sign = encode(msg_enc[2], *encoding['sign'][::-1])
    price = encode(msg_enc[3], *encoding['price'][::-1])
    price = combine_field(price, 3, price_sign)

    size = encode(msg_enc[4], *encoding['size'][::-1])

    delta_t_s = encode(msg_enc[5], *encoding['time'][::-1])

    delta_t_ns = encode(msg_enc[6:9], *encoding['time'][::-1])
    delta_t_ns = combine_field(delta_t_ns, 3)

    time_s = encode(msg_enc[9:11], *encoding['time'][::-1])
    time_s = combine_field(time_s, 3)

    time_ns = encode(msg_enc[11:14], *encoding['time'][::-1])
    time_ns = combine_field(time_ns, 3)

    price_ref_sign = encode(msg_enc[14], *encoding['sign'][::-1])
    price_ref = encode(msg_enc[15], *encoding['price'][::-1])
    price_ref = combine_field(price_ref, 3, price_ref_sign)

    size_ref = encode(msg_enc[16], *encoding['size'][::-1])

    time_s_ref = encode(msg_enc[17:19], *encoding['time'][::-1])
    time_s_ref = combine_field(time_s_ref, 3)

    time_ns_ref = encode(msg_enc[19:22], *encoding['time'][::-1])
    time_ns_ref = combine_field(time_ns_ref, 3)

    return jnp.hstack([
        event_type, direction, price, size, delta_t_s, delta_t_ns, time_s, time_ns,
        price_ref, size_ref, time_s_ref, time_ns_ref])

decode_msgs = jax.jit(jax.vmap(decode_msg, in_axes=(0,)))

class Vocab:

    MASK_TOK = 0
    HIDDEN_TOK = 1
    NA_TOK = 2

    def __init__(self) -> None:
        self.counter = 3  # 0: MSK, 1: HID, 2: NAN
        self.ENCODING = {}
        self.DECODING = {}
        self.DECODING_GLOBAL = {}
        self.TOKEN_DELIM_IDX = {}

        # self._add_field('time', [str(i).zfill(3) for i in range(1000)], [3,6,9,12])
        # self._add_field('event_type', ['1', '2', '3', '4'], None)
        # self._add_field('size', [str(i).zfill(4) for i in range(10000)], [])
        # self._add_field('price', [str(i).zfill(2) for i in range(1000)] + ['+', '-'], [1])
        # self._add_field('direction', ['0', '1'], None)

        self._add_field('time', range(1000), [3,6,9,12])
        self._add_field('event_type', range(1,5), None)
        self._add_field('size', range(10000), [])
        self._add_field('sign', [-1, 1], None)
        self._add_field('price', range(1000), [1])
        self._add_field('direction', [0, 1], None)

        #self._add_field('generic', [str(i) for i in range(10)] + ['+', '-'])
        
        # self._add_special_tokens()

    def __len__(self):
        return self.counter

    def _add_field(self, name, values, delim_i=None):
        # enc = {val: self.counter + i for i, val in enumerate(values)}
        # dec = {tok: val for val, tok in enc.items()}
        # self.ENCODING[name] = enc
        # self.DECODING[name] = dec
        # self.DECODING_GLOBAL.update({tok: (name, val) for val, tok in enc.items()})
        # self.counter += len(enc)
        # self.TOKEN_DELIM_IDX[name] = delim_i

        enc = [(-10000, Vocab.MASK_TOK), (-20000, Vocab.HIDDEN_TOK), (-9999, Vocab.NA_TOK)]
        enc += [(val, self.counter + i) for i, val in enumerate(values)]
        self.counter += len(enc) - 3  # don't count special tokens
        enc = tuple(zip(*enc))
        self.ENCODING[name] = (
            jnp.array(enc[0], dtype=jnp.int32),
            jnp.array(enc[1], dtype=jnp.int32))

    def _add_special_tokens(self):
        for field, enc in self.ENCODING.items():
            self.ENCODING[field]['MSK'] = Vocab.MASK_TOK
            self.ENCODING[field]['HID'] = Vocab.HIDDEN_TOK
            self.ENCODING[field]['NAN'] = Vocab.NA_TOK

            self.DECODING[field][Vocab.MASK_TOK] = 'MSK'
            self.DECODING[field][Vocab.HIDDEN_TOK] = 'HID'
            self.DECODING[field][Vocab.NA_TOK] = 'NAN'
        self.ENCODING['generic'] = {
            'MSK': Vocab.MASK_TOK,
            'HID': Vocab.HIDDEN_TOK,
            'NAN': Vocab.NA_TOK,
        }
        self.DECODING_GLOBAL[Vocab.MASK_TOK] = ('generic', 'MSK')
        self.DECODING_GLOBAL[Vocab.HIDDEN_TOK] = ('generic', 'HID')
        self.DECODING_GLOBAL[Vocab.NA_TOK] = ('generic', 'NAN')

class Message_Tokenizer:

    # FIELDS = (
    #     'time',
    #     'delta_t',
    #     'event_type',
    #     'size',
    #     'price',
    #     'direction',
    #     'time_new',
    #     'delta_t_new',
    #     'event_type_new',
    #     'size_new',
    #     'price_new',
    #     'direction_new'
    # )
    FIELDS = (
        'event_type',
        'direction',
        'price',
        'size',
        'delta_t_s',
        'delta_t_ns',
        'time_s',
        'time_ns',
        # reference fields:
        'price_ref',
        'size_ref',
        'time_s_ref',
        'time_ns_ref',
    )
    N_NEW_FIELDS = 8
    N_REF_FIELDS = 4
    # note: list comps only work inside function for class variables
    FIELD_I = (lambda fields=FIELDS:{
        f: i for i, f in enumerate(fields)
    })()
    #TOK_LENS = np.array((5, 4, 1, 1, 2, 1, 5, 4, 1, 1, 2, 1))
    TOK_LENS = np.array((1, 1, 2, 1, 1, 3, 2, 3, 2, 1, 2, 3))
    TOK_DELIM = np.cumsum(TOK_LENS[:-1])
    #FIELD_DELIM = np.cumsum(FIELD_LENS[:-1])
    MSG_LEN = np.sum(TOK_LENS)
    # encoded message length: total length - length of reference fields
    NEW_MSG_LEN = MSG_LEN - \
        (lambda tl=TOK_LENS, fields=FIELDS: np.sum(tl[i] for i, f in enumerate(fields) if f.endswith('_ref')))()
    # fields in correct message order:
    FIELD_ENC_TYPES = {
        'event_type': 'event_type',
        'direction': 'direction',
        'price': 'price', #'generic',
        'size': 'size', #'generic',
        'delta_t_s': 'time', #'generic',
        'delta_t_ns': 'time',
        'time_s': 'time', #'generic',
        'time_ns': 'time',
        # 'time_new': 'time', #'generic',
        # 'delta_t_new': 'time', #'generic',
        # 'event_type_new': 'event_type',
        # 'size_new': 'size', #'generic',
        # 'price_new': 'price', #'generic',
        # 'direction_new': 'direction',
        'price_ref': 'price',
        'size_ref': 'size',
        'time_s_ref': 'time',
        'time_ns_ref': 'time',
    }

    @staticmethod
    def get_field_from_idx(idx):
        """ Get the field of a given index (or indices) in a message
        """
        if isinstance(idx, int) or idx.ndim == 0:
            idx = np.array([idx])
        if np.any(idx > Message_Tokenizer.MSG_LEN - 1):
            raise ValueError("Index ({}) must be less than {}".format(idx, Message_Tokenizer.MSG_LEN))
        field_i = np.searchsorted(Message_Tokenizer.TOK_DELIM, idx, side='right')
        return [Message_Tokenizer.FIELDS[i] for i in field_i]
    
    @staticmethod
    def _generate_col_idx_by_encoder():
        """ Generates attribute dictionary col_idx_by_encoder
            with encoder type as key and a list of column (field)
            indices as value. This is used to efficiently decode tokenized
            data. 
        """
        col_idx_by_encoder = {}
        counter = 0
        for n_toks, (col, enc_type) in zip(
            Message_Tokenizer.TOK_LENS,
            Message_Tokenizer.FIELD_ENC_TYPES.items()):
            add_vals = list(range(counter, counter + n_toks))
            try:
                col_idx_by_encoder[enc_type].extend(add_vals)
            except KeyError:
                col_idx_by_encoder[enc_type] = add_vals
            counter += n_toks
        return col_idx_by_encoder

    #col_idx_by_encoder = _generate_col_idx_by_encoder.__func__()()

    def __init__(self) -> None:
        self.col_idx_by_encoder = self._generate_col_idx_by_encoder()
        pass

    # def encode(self, m, vocab):
    #     enc = vocab.ENCODING
    #     #m = m.copy()

    #     # order ID is not used by the model
    #     m.drop('order_id', axis=1, inplace=True)

    #     for i, col in enumerate(m.columns):
    #         enc_type = Message_Tokenizer.FIELD_ENC_TYPES[col]
    #         #print(col)
    #         #print(enc_type)
    #         #print(col)
    #         m[col] = self._encode_col(
    #             m[col],
    #             enc=enc[enc_type],
    #             n_toks=Message_Tokenizer.TOK_LENS[i],
    #             delim_i=vocab.TOKEN_DELIM_IDX[enc_type])
    #     # concat all lists into single column
    #     m = m.sum(axis=1)
    #     # return as numpy array
    #     return np.array(m.to_list())
    
    # def encode_field(self, num, field, vocab):
    #     enc_type = Message_Tokenizer.FIELD_ENC_TYPES[field]
    #     enc = vocab.ENCODING[enc_type]
    #     n_toks = Message_Tokenizer.TOK_LENS[Message_Tokenizer.FIELD_I[field]]
    #     delim_i = vocab.TOKEN_DELIM_IDX[enc_type]
    #     return self._encode_field(num, enc, n_toks, delim_i)
    
    # def _encode_field(self, num, enc, n_toks, delim_i=None):
    #     if pd.isnull(num):
    #         return [Vocab.NA_TOK] * n_toks
    #     elif not isinstance(num, str):
    #         num = str(int(num))
    #     if delim_i is not None:
    #         # split into tokenizable junks
    #         num = [num[i:j] for i, j in zip([0] + delim_i, delim_i + [None]) if len(num[i:j]) > 0]
    #     return [enc[d] for d in num]
    #     #return num

    # def _encode_col(self, col, enc, n_toks, delim_i=None):
    #     return col.apply(lambda x: self._encode_field(x, enc, n_toks, delim_i))
    
    # def encode_msg(
    #         self,
    #         msg: np.ndarray,
    #         vocab: Vocab,
    #     ) -> np.ndarray:
    #     """ Encodes a message dictionary into a tokenized numpy array.
    #         Takes the same format as the simulator message dicts
    #         CAVE: this is only ONE HALF of the encoded message
    #     """
    #     # msg = {
    #     #     'timestamp': str(modif_part[0] * 1e-9 + 9.5 * 3600),
    #     #     'type': order_type,
    #     #     'order_id': order_id, 
    #     #     'quantity': removed_quantity,
    #     #     'price': p_mod_raw,
    #     #     'side': 'ask' if side == 0 else 'bid',  # TODO: should be 'buy' or 'sell'
    #     #     'trade_id': 0  # should be trader_id in future
    #     # }

    #     #cols = ['time', 'delta_t', 'event_type', 'size', 'price', 'direction']
    #     enc_types = [self.FIELD_ENC_TYPES[f] for f in Message_Tokenizer.FIELDS if not f.endswith('_ref')]
    #     assert len(enc_types) == len(msg), "Message must have {} fields. Not {}.".format(len(enc_types), len(msg))
    #     out = []
    #     for field, x in zip(enc_types, msg):
    #         # print(field, x)
    #         #enc_type = Message_Tokenizer.FIELD_ENC_TYPES[col]
    #         enc = vocab.ENCODING[field]
    #         delim_i = vocab.TOKEN_DELIM_IDX[field]

    #         if delim_i is not None:
    #             # print('delim_i', delim_i)
    #             # print(len(enc.keys()))
    #             parts = [enc[x[i:j]] for i, j in zip([0] + delim_i, delim_i + [None]) if len(x[i:j]) > 0]
    #         else:
    #             parts = [enc[x]]
    #         # print(parts)
    #         # print()
    #         out.extend(parts)
    #     return np.array(out)

    # def decode_toks(self, toks, vocab):
    #     return int(''.join([vocab.DECODING_GLOBAL[t][1] for t in toks]))
    
    # def decode(self, toks, vocab):
    #     toks = np.array(toks).reshape(-1, Message_Tokenizer.MSG_LEN)
    #     str_arr = self.decode_to_str(toks, vocab)
    #     cols_str = np.split(str_arr, Message_Tokenizer.TOK_DELIM, axis=-1)
    #     out_numeric = np.empty((toks.shape[0], len(cols_str)), dtype=float)
    #     # decode each column to float
    #     for i, inp in enumerate(cols_str):
    #         out_numeric[:, i] = self._parse_col(inp)

    #     return out_numeric
    
    # def decode_to_str(self, toks, vocab, error_on_invalid=False):
    #     # if toks.ndim == 1:
    #     #     toks = np.array(toks).reshape(-1, Message_Tokenizer.MSG_LEN)
    #     # elif toks.ndim >= 2:
    #     #     toks = np.array(toks).reshape(toks.shape[0], -1, Message_Tokenizer.MSG_LEN)
    #     toks = np.array(toks).reshape(-1, Message_Tokenizer.MSG_LEN)
    #     out = np.empty_like(toks, dtype='<U4')
    #     for dec_type, dec in vocab.DECODING.items():
    #         col_msk = np.zeros_like(toks, dtype=bool)
    #         col_msk[..., self.col_idx_by_encoder[dec_type]] = True
    #         for t, repl in dec.items():
    #             #print(((toks == t) * col_msk).shape)
    #             out[(toks == t) * col_msk] = repl

    #     if error_on_invalid:
    #         # left over empty strings imply invalid tokens
    #         err_i = np.argwhere(out == '')
    #         if len(err_i) > 0:
    #             err_toks = toks[tuple(err_i.T)]
    #             #err_toks = toks[out == '']
    #             err_fields = []
    #             for err_sample, err_col in err_i:
    #                 err_fields.append(np.searchsorted(Message_Tokenizer.TOK_DELIM, err_col, side='right'))
    #             e = ValueError(
    #                 f"Invalid tokens {err_toks} at indices {err_i} "
    #                 + f"for fields {[Message_Tokenizer.FIELDS[f] for f in err_fields]})")
    #             e.err_i = err_i
    #             raise e

    #     return out

    # def _parse_col(self, inp):
    #     def try_parse_float(inp):
    #         try:
    #             return float(inp)
    #         except ValueError:
    #             return np.nan
    #     return np.array([try_parse_float(''.join(inp[i])) for i in range(inp.shape[0])])

    def validate(self, toks, vocab):
        """ checks if toks is syntactically AND semantically valid message
            returns triple of (is_valid, error location, error message)
        """
        valid_synt, res = self._validate_syntax(toks, vocab)
        if not valid_synt:
            return False, res, 'syntax error'
        valid_semant, err = self._validate_semantics(res)
        if not valid_semant:
            return False, None, err

    def _validate_syntax(self, toks, vocab):
        try:
            decoded = self.decode_to_str(toks, vocab, error_on_invalid=True)
            return True, decoded
        except ValueError as e:
            return False, e.err_i

    def _validate_semantics(self, decoded):
        ''' checks if decoded message string is semantically correct
            return tuple of (is_valid, error in field, error message)
        '''
        pass

    def invalid_toks_per_msg(self, toks, vocab):
        return (self.decode_to_str(toks, vocab) == '').sum(axis=-1)
    
    def invalid_toks_per_seq(self, toks, vocab):
        return self.invalid_toks_per_msg(toks, vocab).sum(axis=-1)

    # def preproc_OLD(self, m, b, allowed_event_types=[1,2,3,4]):
    #     # TYPE
    #     # filter out only allowed event types ...
    #     m = m.loc[m.event_type.isin(allowed_event_types)].copy()
    #     # ... and corresponding book changes
    #     b = b.loc[m.index]

    #     # TIME
    #     # subtract opening time and convert to ns integer
    #     opening_s = 9.5 * 3600  # NASDAQ opens 9:30
    #     #closing_s = 16 * 3600   # and closes at 16:00
    #     m['time'] = (m['time'] - opening_s).multiply(1e9).round().astype(int)
    #     # DELTA_T: time since previous order --> 4 tokens of length 3
    #     m.insert(
    #         loc=1,
    #         column='delta_t',
    #         value=m['time'].diff().fillna(0).astype(int).round().astype(str).str.zfill(12)
    #     )
    #     m['time'] = m['time'].astype(str).str.zfill(15)
        
    #     # SIZE
    #     m.loc[m['size'] > 9999, 'size'] = 9999
    #     m['size'] = m['size'].astype(int).astype(str).str.zfill(4)

    #     # PRICE
    #     # (previous) best bid
    #     #bb = b.iloc[:, 2].shift()
    #     # rounded mid-price reference
    #     p_ref = ((b.iloc[:, 0] + b.iloc[:, 2]) / 2).round(-2).astype(int).shift()
    #     # --> 1999 price levels // ...00 since tick size is 100
    #     m.price = self._preproc_prices(m.price, p_ref, p_lower_trunc=-99900, p_upper_trunc=99900)
    #     #m = m.dropna()
    #     m = m.iloc[1:]
    #     m.price = m.price.astype(int).apply(self._numeric_str)

    #     # DIRECTION
    #     m.direction = ((m.direction + 1) / 2).astype(int)

    #     # change column order
    #     m = m[['order_id', 'event_type', 'direction', 'price', 'size', 'delta_t', 'time']]

    #     # add original message as feature 
    #     # for all referential order types (2, 3, 4)
    #     m = self._add_orig_msg_features(m)

    #     assert len(m) + 1 == len(b), "length of messages (-1) and book states don't align"

    #     return m
    
    def preproc(self, m, b, allowed_event_types=[1,2,3,4]):
        # TYPE
        # filter out only allowed event types ...
        m = m.loc[m.event_type.isin(allowed_event_types)].copy()
        # ... and corresponding book changes
        b = b.loc[m.index]

        # TIME
        # DELTA_T: time since previous order --> 4 tokens of length 3
        m.insert(
            loc=1,
            column='delta_t_ns',
            value=m['time'].diff().fillna(0)
        )
        m.insert(
            loc=1,
            column='delta_t_s',
            value=m.delta_t_ns.astype(int)
        )
        m.delta_t_ns = ((m.delta_t_ns - m.delta_t_s) * 1e9).astype(int)

        # subtract opening time and convert to ns integer
        opening_s = 9.5 * 3600  # NASDAQ opens 9:30
        #closing_s = 16 * 3600   # and closes at 16:00
        m['time'] = (m['time'] - opening_s)#.multiply(1e9)
        # split time into time before and after decimal point to fit into int32 for jax
        m.insert(0, 'time_s', m.time.astype(int))
        m.rename(columns={'time': 'time_ns'}, inplace=True)
        m.time_ns = ((m.time_ns - m.time_s) * 1e9).astype(int)
        
        # SIZE
        m.loc[m['size'] > 9999, 'size'] = 9999
        m['size'] = m['size'].astype(int)

        # PRICE
        # (previous) best bid
        #bb = b.iloc[:, 2].shift()
        # mid-price reference, rounded down to nearest tick_size
        tick_size = 100
        p_ref = ((b.iloc[:, 0] + b.iloc[:, 2]) / 2)#.round(-2).astype(int).shift()
        p_ref = (p_ref // tick_size) * tick_size
        # --> 1999 price levels // ...00 since tick size is 100
        m.price = self._preproc_prices(m.price, p_ref, p_lower_trunc=-99900, p_upper_trunc=99900)
        m = m.iloc[1:]
        m.price = m.price.astype(int)

        # DIRECTION
        m.direction = ((m.direction + 1) / 2).astype(int)

        # change column order
        m = m[['order_id', 'event_type', 'direction', 'price', 'size',
               'delta_t_s', 'delta_t_ns', 'time_s', 'time_ns']]

        # add original message as feature 
        # for all referential order types (2, 3, 4)
        m = self._add_orig_msg_features(
            m,
            modif_fields=['price', 'size', 'time_s', 'time_ns'])

        # order ID is not used by the model
        m.drop('order_id', axis=1, inplace=True)

        assert len(m) + 1 == len(b), "length of messages (-1) and book states don't align"

        return m.values

    def _preproc_prices(self, p, p_ref, p_lower_trunc=-1000, p_upper_trunc=1300):
        """ Takes prices series and reference price (best bid or mid price), 
            encoding prices relative to reference price.
            Returns scaled price series
        """
        # encode prices relative to (previous) refernce price
        p = p - p_ref
        # truncate price at deviation of x
        # min tick is 100, hence min 10-level diff is 900
        # <= 1000 covers ~99.54% on bid side, ~99.1% on ask size (GOOG)
        pct_changed = 100 * len(p.loc[p > p_upper_trunc]) / len(p)
        print(f"truncating {pct_changed:.4f}% of prices > {p_upper_trunc}")
        p.loc[p > p_upper_trunc] = p_upper_trunc
        pct_changed = 100 * len(p.loc[p < p_lower_trunc]) / len(p)
        print(f"truncating {pct_changed:.4f}% of prices < {p_lower_trunc}")
        p.loc[p < p_lower_trunc] = p_lower_trunc
        # scale prices to min ticks size differences
        p /= 100
        return p

    # def _add_orig_msg_features(self, m):
    #     """ Changes representation of order cancellation (2) / deletion (3) / execution (4),
    #         representing them as the original message and new columns containing
    #         the order modification details.
    #         This effectively does the lookup step in past data.
    #         TODO: lookup missing original message data from previous days' data?
    #     """

    #     m_changes = pd.merge(
    #         m.loc[m.event_type == 1],
    #         m.loc[(m.event_type == 2) | (m.event_type == 3) | (m.event_type == 4)].reset_index(),
    #         how='right', on='order_id', suffixes=['', '_new']).set_index('index')
    #     #display(m_changes)

    #     # add new empty columns for order modifications
    #     m[m_changes.columns[m.shape[1]:].values] = np.nan
    #     # replace order changes by original order and additional new fields
    #     #display(m)
    #     #display(m_changes)
    #     m.loc[m_changes.index] = m_changes
    #     return m

    def _add_orig_msg_features(
            self,
            m,
            modif_types={2,3,4},
            modif_fields=['price', 'size', 'time'],
            nan_val=-9999
        ):
        """ Changes representation of order cancellation (2) / deletion (3) / execution (4),
            representing them as the original message and new columns containing
            the order modification details.
            This effectively does the lookup step in past data.
            TODO: lookup missing original message data from previous days' data?
        """

        m_changes = pd.merge(
            m.loc[m.event_type.isin(modif_types)].reset_index(),
            m.loc[m.event_type == 1, ['order_id'] + modif_fields],
            how='left', on='order_id', suffixes=['', '_ref']).set_index('index')
        #display(m_changes)

        # add new empty columns for referenced order
        modif_cols = [field + '_ref' for field in modif_fields]
        m[modif_cols] = nan_val
        # replace order changes by original order and additional new fields
        #display(m)
        #display(m_changes)
        m.loc[m_changes.index] = m_changes
        m[modif_cols] = m[modif_cols].fillna(nan_val).astype(int)
        return m
    
    def _numeric_str(self, num, pad=2):
        if num == 0:
            return '-00'
        elif num > 0:
            return '+' + str(num).zfill(pad)
        else:
            # minus sign counts as character
            return str(num).zfill(pad + 1)
