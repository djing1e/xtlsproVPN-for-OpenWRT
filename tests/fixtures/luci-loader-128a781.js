/* SPDX-License-Identifier: Apache-2.0
 * See LICENSE.luci for the upstream license.
 * Class and module loader excerpts from OpenWrt LuCI commit 128a781.
 * https://github.com/openwrt/luci/blob/128a781/modules/luci-base/htdocs/luci-static/resources/luci.js
 * Kept verbatim; test harness supplies DOM/HTTP and built-in modules.
 */
module.exports = function(classes, Request, env, window, document) {
	const toCamelCase = s => s.replace(/(?:^|[. -])(.)/g, (m0, m1) => m1.toUpperCase());

	/**
	 * @class 
	 * @name LuCI.baseclass
	 * @hideconstructor
	 * @classdesc
	 *
	 * `LuCI.baseclass` is the abstract base class all LuCI classes inherit from.
	 *
	 * It provides a simple means to create subclasses of given classes and
	 * implements prototypal inheritance.
	 */
	const superContext = {};

	let classIndex = 0;

	const Class = Object.assign(function() {}, {
		/**
		 * Extends this base class with the properties described in
		 * `properties` and returns a new subclassed Class instance
		 *
		 * @memberof LuCI.baseclass
		 *
		 * @param {Object<string, *>} properties
		 * An object describing the properties to add to the new
		 * subclass.
		 *
		 * @this {LuCI.baseclass}
		 * @returns {LuCI.baseclass}
		 * Returns a new LuCI.baseclass subclassed from this class, extended
		 * by the given properties and with its prototype set to this base
		 * class to enable inheritance. The resulting value represents a
		 * class constructor and can be instantiated with `new`.
		 */
		extend(properties) {
			const props = {
				__id__: { value: classIndex },
				__base__: { value: this.prototype },
				__name__: { value: properties.__name__ ?? `anonymous${classIndex++}` }
			};

			const ClassConstructor = function() {
				if (!(this instanceof ClassConstructor))
					throw new TypeError('Constructor must not be called without "new"');

				if (Object.getPrototypeOf(this).hasOwnProperty('__init__')) {
					if (typeof(this.__init__) != 'function')
						throw new TypeError('Class __init__ member is not a function');

					this.__init__.apply(this, arguments)
				}
				else {
					this.super('__init__', arguments);
				}
			};

			for (const key in properties)
				if (!props[key] && properties.hasOwnProperty(key))
					props[key] = { value: properties[key], writable: true };

			ClassConstructor.prototype = Object.create(this.prototype, props);
			ClassConstructor.prototype.constructor = ClassConstructor;
			Object.assign(ClassConstructor, this);
			ClassConstructor.displayName = toCamelCase(`${props.__name__.value}Class`);

			return ClassConstructor;
		},

		/**
		 * Extends this base class with the properties described in
		 * `properties`, instantiates the resulting subclass using
		 * the given arguments passed to this function
		 * and returns the resulting subclassed Class instance.
		 *
		 * This function serves as a convenience shortcut for
		 * {@link LuCI.baseclass.extend Class.extend()} and subsequent
		 * `new`.
		 *
		 * @memberof LuCI.baseclass
		 *
		 * @param {Object<string, *>} properties
		 * An object describing the properties to add to the new
		 * subclass.
		 *
		 * @param {...*} new_args
		 * Arguments forwarded to the constructor of the generated subclass.
		 *
		 * @returns {LuCI.baseclass}
		 * Returns a new LuCI.baseclass instance extended by the given
		 * properties with its prototype set to this base class to
		 * enable inheritance.
		 */
		singleton(properties, ...new_args) {
			return Class.extend(properties).instantiate(new_args);
		},

		/**
		 * Calls the class constructor using `new` with the given argument
		 * array being passed as variadic parameters to the constructor.
		 *
		 * @memberof LuCI.baseclass
		 *
		 * @param {Array<*>} args
		 * An array of arbitrary values which will be passed as arguments
		 * to the constructor function.
		 *
		 * @returns {LuCI.baseclass}
		 * Returns a new LuCI.baseclass instance extended by the given
		 * properties with its prototype set to this base class to
		 * enable inheritance.
		 */
		instantiate(args) {
			return new (Function.prototype.bind.call(this, null, ...args))();
		},

		/* unused */
		call(self, method, ...args) {
			if (typeof(this.prototype[method]) != 'function')
				throw new ReferenceError(`${method} is not defined in class`);

			return this.prototype[method].call(self, method, ...args);
		},

		/**
		 * Checks whether the given class value is a subclass of this class.
		 *
		 * @memberof LuCI.baseclass
		 *
		 * @param {LuCI.baseclass} classValue
		 * The class object to test.
		 *
		 * @returns {boolean}
		 * Returns `true` when the given `classValue` is a subclass of this
		 * class or `false` if the given value is not a valid class or not
		 * a subclass of this class.
		 */
		isSubclass(classValue) {
			return (typeof(classValue) == 'function' && classValue.prototype instanceof this);
		},

		prototype: {
			/**
			 * Extract all values from the given argument array beginning from
			 * `offset` and prepend any further given optional parameters to
			 * the beginning of the resulting array copy.
			 *
			 * @memberof LuCI.baseclass.prototype
			 * @instance
			 *
			 * @param {Array<*>} args
			 * The array to extract the values from.
			 *
			 * @param {number} offset
			 * The offset from which to extract the values. An offset of `0`
			 * would copy all values till the end.
			 *
			 * @param {...*} [extra_args]
			 * Extra arguments to add to prepend to the resulting array.
			 *
			 * @returns {Array<*>}
			 * Returns a new array consisting of the optional extra arguments
			 * and the values extracted from the `args` array beginning with
			 * `offset`.
			 */
			varargs(args, offset, ...extra_args) {
				return extra_args.concat(Array.prototype.slice.call(args, offset));
			},

			/**
			 * Walks up the parent class chain and looks for a class member
			 * called `key` in any of the parent classes this class inherits
			 * from. Returns the member value of the superclass or calls the
			 * member as a function and returns its return value when the
			 * optional `callArgs` array is given.
			 *
			 * This function has two signatures and is sensitive to the
			 * amount of arguments passed to it:
			 *  - `super('key')` -
			 *	Returns the value of `key` when found within one of the
			 *	parent classes.
			 *  - `super('key', ['arg1', 'arg2'])` -
			 *	Calls the `key()` method with parameters `arg1` and `arg2`
			 *	when found within one of the parent classes.
			 *
			 * @memberof LuCI.baseclass.prototype
			 * @instance
			 *
			 * @param {string} key
			 * The name of the superclass member to retrieve.
			 *
			 * @param {...*|Array<*>} [callArgs]
			 * Arguments to pass when invoking the superclass method. May be 
			 * either an argument array or variadic arguments.
			 *
			 * @throws {ReferenceError}
			 * Throws a `ReferenceError` when `callArgs` are specified and
			 * the found member named by `key` is not a function value.
			 *
			 * @returns {*|null}
			 * Returns the value of the found member or the return value of
			 * the call to the found method. Returns `null` when no member
			 * was found in the parent class chain or when the call to the
			 * superclass method returned `null`.
			 */
			super(key, ...callArgs) {
				if (key == null)
					return null;

				const slotIdx = `${this.__id__}.${key}`;
				const symStack = superContext[slotIdx];
				let protoCtx = null;

				for (protoCtx = Object.getPrototypeOf(symStack ? symStack[0] : Object.getPrototypeOf(this));
					 protoCtx != null && !protoCtx.hasOwnProperty(key);
					 protoCtx = Object.getPrototypeOf(protoCtx)) {}

				if (protoCtx == null)
					return null;

				let res = protoCtx[key];

				if (callArgs.length > 0) {
					if (typeof(res) != 'function')
						throw new ReferenceError(`${key} is not a function in base class`);

					if (Array.isArray(callArgs[0]) || LuCI.prototype.isArguments(callArgs[0]))
						callArgs = callArgs[0];

					if (symStack)
						symStack.unshift(protoCtx);
					else
						superContext[slotIdx] = [ protoCtx ];

					res = res.apply(this, callArgs);

					if (symStack && symStack.length > 1)
						symStack.shift(protoCtx);
					else
						delete superContext[slotIdx];
				}

				return res;
			},

			/**
			 * Returns a string representation of this class.
			 *
			 * @memberof LuCI.baseclass.prototype
			 * @instance
			 *
			 * @returns {string}
			 * Returns a string representation of this class containing the
			 * constructor functions `displayName` and describing the class
			 * members and their respective types.
			 */
			toString() {
				let s = `[${this.constructor.displayName}]`, f = true;
				for (const k in this) {
					if (this.hasOwnProperty(k)) {
						s += `${f ? ' {\n' : ''}  ${k}: ${typeof(this[k])}\n`;
						f = false;
					}
				}
				return s + (f ? '' : '}');
			}
		}
	});


 let LuCI = function() {};
 LuCI.prototype = {
  isArguments(value) { return Object.prototype.toString.call(value) === "[object Arguments]"; },
  error(type, text, ...args) { throw new TypeError(text.format(...args)); },
  raise(type, text, ...args) { throw new Error(text.format(...args)); },
		require(name, from = []) {
			const L = this;
			let url = null;

			/* Class already loaded */
			if (classes[name] != null) {
				/* Circular dependency */
				if (from.indexOf(name) != -1)
					LuCI.prototype.raise('DependencyError',
						'Circular dependency: class "%s" depends on "%s"',
						name, from.join('" which depends on "'));

				return Promise.resolve(classes[name]);
			}

			url = '%s/%s.js%s'.format(env.base_url, name.replace(/\./g, '/'), (env.resource_version ? `?v=${env.resource_version}` : ''));
			from = [ name ].concat(from);

			const compileClass = res => {
				if (!res.ok)
					LuCI.prototype.raise('NetworkError',
						'HTTP error %d while loading class file "%s"', res.status, url);

				const source = res.text();
				const requirematch = /^require[ \t]+(\S+)(?:[ \t]+as[ \t]+([a-zA-Z_]\S*))?$/;
				const strictmatch = /^use[ \t]+strict$/;
				const depends = [];
				let args = '';

				/* find require statements in source */
				for (let i = 0, off = -1, prev = -1, quote = -1, comment = -1, esc = false; i < source.length; i++) {
					const chr = source.charCodeAt(i);

					if (esc) {
						esc = false;
					}
					else if (comment != -1) {
						if ((comment == 47 && chr == 10) || (comment == 42 && prev == 42 && chr == 47))
							comment = -1;
					}
					else if ((chr == 42 || chr == 47) && prev == 47) {
						comment = chr;
					}
					else if (chr == 92) {
						esc = true;
					}
					else if (chr == quote) {
						const s = source.substring(off, i), m = requirematch.exec(s);

						if (m) {
							const dep = m[1], as = m[2] || dep.replace(/[^a-zA-Z0-9_]/g, '_');
							depends.push(LuCI.prototype.require(dep, from));
							args += `, ${as}`;
						}
						else if (!strictmatch.exec(s)) {
							break;
						}

						off = -1;
						quote = -1;
					}
					else if (quote == -1 && (chr == 34 || chr == 39)) {
						off = i + 1;
						quote = chr;
					}

					prev = chr;
				}

				/* load dependencies and instantiate class */
				return Promise.all(depends).then(instances => {
					let _factory, _class;

					try {
						_factory = eval(
							'(function(window, document, L%s) { %s })\n\n//# sourceURL=%s\n'
								.format(args, source, res.url));
					}
					catch (error) {
						LuCI.prototype.raise('SyntaxError', '%s\n  in %s:%s',
							error.message, res.url, error.lineNumber ?? '?');
					}

					_factory.displayName = toCamelCase(`${name}ClassFactory`);
					_class = _factory.apply(_factory, [window, document, L].concat(instances));

					if (!Class.isSubclass(_class))
						LuCI.prototype.error('TypeError', '"%s" factory yields invalid constructor', name);

					if (_class.displayName == 'AnonymousClass')
						_class.displayName = toCamelCase(`${name}Class`);

					let ptr = Object.getPrototypeOf(L);
					let idx = 0;
					const parts = name.split(/\./);
					const instance = new _class();

					while (ptr && idx < parts.length - 1)
						ptr = ptr[parts[idx++]];

					if (ptr)
						ptr[parts[idx]] = instance;

					classes[name] = instance;

					return instance;
				});
			};

			/* Request class file */
			classes[name] = Request.get(url, { cache: true }).then(compileClass);

			return classes[name];
		},
 };
 return { Class, L: Object.assign(Object.create(LuCI.prototype), { Class }) };
};

